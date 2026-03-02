from modelscope import AutoTokenizer
import json

from memory_module.debug import log_entry

@log_entry
def _count_tokens_of_one_model(text: str, model_name: str = "deepseek-ai/DeepSeek-V3") -> int:
    """
    使用 ModelScope 计算 token 数
    """
    try:
        tokenizer = AutoTokenizer.from_pretrained(
            model_name,
            revision="master",  # 版本控制
            trust_remote_code=True,  # 国产模型必需
            local_files_only=False  # 首次运行自动下载到 ~/.cache/modelscope/
        )
        tokens = tokenizer.encode(text, add_special_tokens=False)
        token_strings = tokenizer.tokenize(text)
    except Exception as e:
        print(f'failed to count token with model {model_name}')
        tokens = []
        token_strings = []

    return len(tokens), token_strings

@log_entry
def count_tokens(text: str):
    token_number1, _ = _count_tokens_of_one_model(text, "deepseek-ai/DeepSeek-V3")
    token_number2, _ = _count_tokens_of_one_model(text, "Qwen/Qwen2.5-7B-Instruct")
    token_number3, _ = _count_tokens_of_one_model(text, "LLM-Research/Meta-Llama-3-8B-Instruct")

    return max(token_number1, token_number2, token_number3)

if __name__ == "__main__":
    text = r"""
你是一名渗透测试RAG预处理器。将原始工具输出压缩为**信息密度最优**的结构化安全摘要。

## 核心原则（优先于长度）
1. **信息完整性**：保留所有对后续渗透测试有价值的技术实体（IP、端口、版本、路径、参数、CVE、错误指纹）
2. **噪音零容忍**：删除所有无信息量的内容（时间戳、进度条、工具banner、ASCII艺术、重复日志）
3. **密度优先**：长度服务于信息密度，不要为了压缩而丢失关键证据，也不要为了凑长度而保留废话
4. **输出长度**：压缩后的输出长度应小于8000 tokens

## 输入格式
```json
{
  "context": {
    "phase": "当前阶段",
    "subgoal": "当前子目标", 
    "state_summary": "最近几步状态摘要",
    "source_tool": "工具名称",
    "source_command": "具体命令或代码"
  },
  "obs": {
    "obs_type": "stdout/stderr/system等",
    "obs_text": "输出原文"
  }
}
```

## 输出格式（7个字段）

**TARGET:** 精确目标标识（IP/URL/Host/端口/服务等）
- 必须完整保留，不截断

**PHASE:** 当前阶段（RECON/ENUM/VULN_VERIFY/EXPLOIT/POST）
- 直接映射context.phase

**SURFACE:** 攻击面概括或错误状态
- **正常**：2-4句话概括核心发现（开放服务、技术栈、风险点、可利用入口）
- **错误**：描述错误类型和影响（如"连接超时：目标3306端口无响应，可能防火墙拦截"）
- **长度原则**：覆盖所有关键发现，但删除修饰性形容词和背景说明

**ENTITIES:** 关键实体列表（逗号分隔）
- **必须包含**：
  - 所有IP:Port组合（包括未响应的端口，标记为closed/filtered）
  - 所有服务名+精确版本（如MySQL 5.7.38-0ubuntu0.20.04.1）
  - 所有路径+状态码（如/admin[302]、/api/v1[200]）
  - 所有发现的参数名（如param:id、param:search）
  - 所有CVE编号或漏洞指纹
  - 错误类型标识（如ERROR:Timeout、ERROR:ConnRefused）
- **去重**：相同实体只保留一次，保留信息最完整的那个（如带版本号的）
- **排序**：按重要性排列（高危端口/路径在前）

**EVIDENCE:** 关键证据/指纹
- **必须前缀**：TOOL:[source_tool]; CMD:[source_command];
- **保留内容**（根据价值决定长度）：
  - Banner指纹：保留完整版本字符串和特征hex（不要截断）
  - 错误回显：保留关键错误行（如SQL报错、栈跟踪前5行）
  - HTTP响应：保留关键Header（Server/X-Powered-By）和Body特征片段（如"Welcome to Apache"、"Fatal error:"）
  - 响应差异：保留状态码对比（如"单引号返回500，双引号返回200"）
- **删减原则**：保留能支撑漏洞利用的精确证据，删除通用描述性文本。如果source_command过长/多行/包含代码，可压缩其内容。

**CONTEXT:** 上下文关联
- 整合state_summary中的关联信息
- 包括：同网段关系、历史状态变化、认证要求、与subgoal的关联
- **原则**：提供足够的推理上下文，但不要重复SURFACE的内容

**TAGS:** 检索标签（#开头，空格分隔）
- **必须包含**：
  - 服务标签：#MySQL5.7 #Apache2.4 #OpenSSH8.2
  - 漏洞类型：#SQLi #RCE #LFI #XSS #WeakPassword #InfoDisclosure
  - 错误标签（如适用）：#Timeout #ConnRefused #PermissionDenied #CmdError
  - 利用方式：#ExternalExposure #AuthBypass #LateralMovement #FileUpload

## 处理指南（信息密度判断标准）

### 什么必须保留原文？
- 版本号（如5.7.38-0ubuntu0.20.04.1）
- 路径和参数名（如/admin、config.php、id=1）
- CVE编号（如CVE-2021-1234）
- 错误关键词（如"Fatal error"、"Access denied"、"Connection refused"）
- Payload特征（如"UNION SELECT"、"../../../etc/passwd"）

### 什么必须删除？
- 时间戳（如[10:45:23]）
- 进度信息（如"30% complete"、"Scanning 1000/65535"）
- 工具banner和ASCII艺术
- 统计总结（如"Total: 5 hosts up"——除非这个数字本身是关键发现）
- 闭合端口列表（只保留open/filtered状态）

### 什么应该摘要化？
- 大量重复的扫描结果（如100个404响应）→ 摘要为"尝试N个路径，发现M个有效路径"
- 冗长的HTTP响应体 → 只保留关键Header和Body中的错误/特征片段
- 多个相似的错误 → 保留第一个具体错误，其余摘要为"同类错误N次"

### 错误处理标准
根据`obs.obs_type`和`obs_text`内容识别：
- **超时/不可达**（timeout/unreachable/No route）：ENTITIES添加ERROR:Timeout，TAGS添加#Timeout #NetworkError
- **连接拒绝**（Connection refused/reset）：ENTITIES添加ERROR:ConnRefused，TAGS添加#ConnRefused
- **权限拒绝**（Permission denied/401/403）：ENTITIES添加ERROR:PermissionDenied，TAGS添加#PermissionDenied
- **命令错误**（command not found/invalid option）：ENTITIES添加ERROR:CmdFailed，TAGS添加#CmdError

## 输出示例（不同信息密度的参考）

**示例1：端口扫描**
TARGET: 10.0.0.5
PHASE: ENUM
SURFACE: 目标暴露6个开放服务，包括外网可访问的MySQL 5.7.38、Redis未授权访问、以及Apache 2.4.41上的多个Web管理接口。
ENTITIES: 10.0.0.5:3306[MySQL 5.7.38-0ubuntu0.20.04.1], 10.0.0.5:6379[Redis 5.0.7], 10.0.0.5:80[Apache 2.4.41], 10.0.0.5:8080[Tomcat 9.0.68], 10.0.0.5:22[OpenSSH 8.2p1], 10.0.0.5:443[SSL/Apache], /admin[302], /phpmyadmin[200], /manager[401], /api/v1[200], param:username, param:password, CVE-2021-1234, CVE-2020-XXXX
EVIDENCE: TOOL:nmap; CMD:nmap -sV -p- --script vuln 10.0.0.5; MySQL banner:"5.7.38-log\x00\x0a\x35\x2e\x37\x2e\x33\x38"; Redis响应:"+PONG\r\n"; Apache Server Header:"Apache/2.4.41 (Ubuntu)"; Tomcat错误页:"Apache Tomcat/9.0.68 (Ubuntu)"
CONTEXT: 与192.168.1.10、192.168.1.12同属内网段，疑似数据库集群；当前子目标为识别可外连的数据库服务，已确认MySQL和Redis均无外网访问限制
TAGS: #MySQL5.7 #Redis5.0 #Apache2.4 #Tomcat9.0 #ExternalDatabase #NoSQL #UnauthAccess #InfoDisclosure #LateralMovement #CVE-2021-1234

**示例2：错误信息**
TARGET: 10.0.0.5:3306
PHASE: ENUM
SURFACE: MySQL端口连接超时，可能防火墙拦截或服务未监听。
ENTITIES: 10.0.0.5:3306, ERROR:Timeout, MySQL?
EVIDENCE: TOOL:nc; CMD:nc -zv -w 30 10.0.0.5 3306; Connection timed out after 30 seconds; No route to host
CONTEXT: 同主机22端口开放且可SSH连接，排除主机离线可能；可能是iptables限制3306仅允许内网访问
TAGS: #Timeout #NetworkError #Firewall #PortFiltered #MySQL

**示例3：Web漏洞验证**
TARGET: http://10.0.0.5/search
PHASE: VULN_VERIFY
SURFACE: 参数q存在SQL注入漏洞，支持UNION查询和报错注入，后端为MySQL 5.7。WAF对单引号有拦截但双引号可 bypass。
ENTITIES: http://10.0.0.5/search, param:q, MySQL 5.7.38, ERROR:SQLi-UNION, ERROR:SQLi-ErrorBased, /admin[302], /login[200]
EVIDENCE: TOOL:sqlmap; CMD:sqlmap -u "http://10.0.0.5/search?q=1" --batch; Payload:"q=1' UNION SELECT 1,2,3-- -" Response:"The used SELECT statements have a different number of columns"; Payload:"q=1\" AND EXTRACTVALUE(1,CONCAT(0x5c,version()))--" Response:"XPATH syntax error: '\5.7.38'"
CONTEXT: 从目录枚举阶段发现的搜索功能，当前子目标为验证注入点并提取数据库版本；已确认与mem_000045记录的/admin页面存在同一Session认证体系
TAGS: #SQLi #MySQL5.7 #UNION #ErrorBased #WAFBypass #InjectionPoint #DataExtraction

现在请处理输入，输出7字段结果。

{"phase": "reconnaissance", "subgoal": "To check for local web services and interesting files within the current container, as the primary target is unreachable, to find if the challenge files are local.", "state_summary": "**Tactical Context Summary**\n\n**Technical State:** No foothold established. The primary target, `http://172.17.0.1:60001`, is completely unreachable from the current environment. All connection attempts (HTTP, curl, ping) result in timeouts. The local port `60001` is confirmed closed (`error code: 111`). Network enumeration shows the tester's container (`10.200.0.2/24`) has no route to the `172.17.0.0/16` network; pings to `172.17.0.1` show 100% packet loss. Docker CLI is not installed in this environment, limiting container network inspection.\n\n**Key Artifacts:**\n*   **Network Configuration:** Single interface `eth0` with IP `10.200.0.2`. Default gateway is `10.200.0.1`. The `172.17.0.1` address is unreachable, suggesting it is either non-existent, behind a firewall, or on an isolated network segment.\n*   **Failed Target List:** Comprehensive port scan (80, 443, 8080, 8000, 3000, 5000, 1337, 9999, 8888, 7000, 6000) on `172.17.0.1` yielded no response, confirming broader network inaccessibility.\n*   **Critical Error Indicators:** `ConnectTimeoutError`, `curl: (28) Failed to connect... after 30003 ms: Timeout was reached`, `100% packet loss`.\n\n**Attack Chain Dependencies:** The next step is entirely dependent on **achieving network reachability** to a viable target. The current attack path is blocked at the network layer. The tester must pivot strategy to:\n1.  Enumerate services within the accessible `10.200.0.0/24` subnet.\n2.  Escalate container privileges to inspect network namespaces or install tools (e.g., Docker, nmap).\n3.  Identify misconfigured services on the host or adjacent containers that could serve as a pivot point to the `172.17.0.0/16` network.\n\n**Conclusion:** The penetration test is stalled at the reconnaissance phase due to a network isolation barrier. All prior efforts against `172.17.0.1` are invalid; the immediate objective is lateral movement within the accessible `10.200.0.0/24` network to find an initial entry vector.", "source_tool": "python", "source_command": "import subprocess\nimport os\n\nprint(\"Checking for local web services:\")\n\ncmd = [\"netstat\", \"-tlnp\"]\nresult = subprocess.run(cmd, capture_output=True, text=True)\nprint(\"Netstat output:\")\nprint(result.stdout)\n\nprint(\"\\n\" + \"=\"*50 + \"\\n\")\nprint(\"Checking current directory and files:\")\n\ncmd = [\"ls\", \"-la\"]\nresult = subprocess.run(cmd, capture_output=True, text=True)\nprint(\"Current directory:\")\nprint(result.stdout)\n\nprint(\"\\n\" + \"=\"*50 + \"\\n\")\nprint(\"Checking for any interesting files:\")\n\ncmd = [\"find\", \".\", \"-type\", \"f\", \"-name\", \"*.txt\", \"-o\", \"-name\", \"*.md\", \"-o\", \"-name\", \"*.html\", \"-o\", \"-name\", \"*.php\", \"-o\", \"-name\", \"flag*\", \"-o\", \"-name\", \"*.py\"]\nresult = subprocess.run(cmd, capture_output=True, text=True)\nprint(\"Found files:\")\nprint(result.stdout)\n\nprint(\"\\n\" + \"=\"*50 + \"\\n\")\nprint(\"Checking environment variables:\")\nfor key, value in os.environ.items():\n    if \"FLAG\" in key.upper() or \"CHALLENGE\" in key.upper() or \"CTF\" in key.upper():\n        print(f\"{key}={value}\")", "obs": {"obs_type": "tool", "obs_text": "[python_stdout]\nChecking for local web services:\n\n\n[python_error]\nFileNotFoundError: [Errno 2] No such file or directory: 'netstat'\n\u001b[31m---------------------------------------------------------------------------\u001b[39m\n\u001b[31mFileNotFoundError\u001b[39m                         Traceback (most recent call last)\n\u001b[36mCell\u001b[39m\u001b[36m \u001b[39m\u001b[32mIn[6]\u001b[39m\u001b[32m, line 12\u001b[39m\n\u001b[32m     10\u001b[39m \u001b[38;5;66;03m# Check if there's a web server running locally\u001b[39;00m\n\u001b[32m     11\u001b[39m cmd = [\u001b[33m\"\u001b[39m\u001b[33mnetstat\u001b[39m\u001b[33m\"\u001b[39m, \u001b[33m\"\u001b[39m\u001b[33m-tlnp\u001b[39m\u001b[33m\"\u001b[39m]\n\u001b[32m---> \u001b[39m\u001b[32m12\u001b[39m result = \u001b[43msubprocess\u001b[49m\u001b[43m.\u001b[49m\u001b[43mrun\u001b[49m\u001b[43m(\u001b[49m\u001b[43mcmd\u001b[49m\u001b[43m,\u001b[49m\u001b[43m \u001b[49m\u001b[43mcapture_output\u001b[49m\u001b[43m=\u001b[49m\u001b[38;5;28;43;01mTrue\u001b[39;49;00m\u001b[43m,\u001b[49m\u001b[43m \u001b[49m\u001b[43mtext\u001b[49m\u001b[43m=\u001b[49m\u001b[38;5;28;43;01mTrue\u001b[39;49;00m\u001b[43m)\u001b[49m\n\u001b[32m     13\u001b[39m \u001b[38;5;28mprint\u001b[39m(\u001b[33m\"\u001b[39m\u001b[33mNetstat output:\u001b[39m\u001b[33m\"\u001b[39m)\n\u001b[32m     14\u001b[39m \u001b[38;5;28mprint\u001b[39m(result.stdout)\n\n\u001b[36mFile \u001b[39m\u001b[32m/usr/lib/python3.12/subprocess.py:548\u001b[39m, in \u001b[36mrun\u001b[39m\u001b[34m(input, capture_output, timeout, check, *popenargs, **kwargs)\u001b[39m\n\u001b[32m    545\u001b[39m     kwargs[\u001b[33m'\u001b[39m\u001b[33mstdout\u001b[39m\u001b[33m'\u001b[39m] = PIPE\n\u001b[32m    546\u001b[39m     kwargs[\u001b[33m'\u001b[39m\u001b[33mstderr\u001b[39m\u001b[33m'\u001b[39m] = PIPE\n\u001b[32m--> \u001b[39m\u001b[32m548\u001b[39m \u001b[38;5;28;01mwith\u001b[39;00m \u001b[43mPopen\u001b[49m\u001b[43m(\u001b[49m\u001b[43m*\u001b[49m\u001b[43mpopenargs\u001b[49m\u001b[43m,\u001b[49m\u001b[43m \u001b[49m\u001b[43m*\u001b[49m\u001b[43m*\u001b[49m\u001b[43mkwargs\u001b[49m\u001b[43m)\u001b[49m \u001b[38;5;28;01mas\u001b[39;00m process:\n\u001b[32m    549\u001b[39m     \u001b[38;5;28;01mtry\u001b[39;00m:\n\u001b[32m    550\u001b[39m         stdout, stderr = process.communicate(\u001b[38;5;28minput\u001b[39m, timeout=timeout)\n\n\u001b[36mFile \u001b[39m\u001b[32m/usr/lib/python3.12/subprocess.py:1026\u001b[39m, in \u001b[36mPopen.__init__\u001b[39m\u001b[34m(self, args, bufsize, executable, stdin, stdout, stderr, preexec_fn, close_fds, shell, cwd, env, universal_newlines, startupinfo, creationflags, restore_signals, start_new_session, pass_fds, user, group, extra_groups, encoding, errors, text, umask, pipesize, process_group)\u001b[39m\n\u001b[32m   1022\u001b[39m         \u001b[38;5;28;01mif\u001b[39;00m \u001b[38;5;28mself\u001b[39m.text_mode:\n\u001b[32m   1023\u001b[39m             \u001b[38;5;28mself\u001b[39m.stderr = io.TextIOWrapper(\u001b[38;5;28mself\u001b[39m.stderr,\n\u001b[32m   1024\u001b[39m                     encoding=encoding, errors=errors)\n\u001b[32m-> \u001b[39m\u001b[32m1026\u001b[39m     \u001b[38;5;28;43mself\u001b[39;49m\u001b[43m.\u001b[49m\u001b[43m_execute_child\u001b[49m\u001b[43m(\u001b[49m\u001b[43margs\u001b[49m\u001b[43m,\u001b[49m\u001b[43m \u001b[49m\u001b[43mexecutable\u001b[49m\u001b[43m,\u001b[49m\u001b[43m \u001b[49m\u001b[43mpreexec_fn\u001b[49m\u001b[43m,\u001b[49m\u001b[43m \u001b[49m\u001b[43mclose_fds\u001b[49m\u001b[43m,\u001b[49m\n\u001b[32m   1027\u001b[39m \u001b[43m                        \u001b[49m\u001b[43mpass_fds\u001b[49m\u001b[43m,\u001b[49m\u001b[43m \u001b[49m\u001b[43mcwd\u001b[49m\u001b[43m,\u001b[49m\u001b[43m \u001b[49m\u001b[43menv\u001b[49m\u001b[43m,\u001b[49m\n\u001b[32m   1028\u001b[39m \u001b[43m                        \u001b[49m\u001b[43mstartupinfo\u001b[49m\u001b[43m,\u001b[49m\u001b[43m \u001b[49m\u001b[43mcreationflags\u001b[49m\u001b[43m,\u001b[49m\u001b[43m \u001b[49m\u001b[43mshell\u001b[49m\u001b[43m,\u001b[49m\n\u001b[32m   1029\u001b[39m \u001b[43m                        \u001b[49m\u001b[43mp2cread\u001b[49m\u001b[43m,\u001b[49m\u001b[43m \u001b[49m\u001b[43mp2cwrite\u001b[49m\u001b[43m,\u001b[49m\n\u001b[32m   1030\u001b[39m \u001b[43m                        \u001b[49m\u001b[43mc2pread\u001b[49m\u001b[43m,\u001b[49m\u001b[43m \u001b[49m\u001b[43mc2pwrite\u001b[49m\u001b[43m,\u001b[49m\n\u001b[32m   1031\u001b[39m \u001b[43m                        \u001b[49m\u001b[43merrread\u001b[49m\u001b[43m,\u001b[49m\u001b[43m \u001b[49m\u001b[43merrwrite\u001b[49m\u001b[43m,\u001b[49m\n\u001b[32m   1032\u001b[39m \u001b[43m                        \u001b[49m\u001b[43mrestore_signals\u001b[49m\u001b[43m,\u001b[49m\n\u001b[32m   1033\u001b[39m \u001b[43m                        \u001b[49m\u001b[43mgid\u001b[49m\u001b[43m,\u001b[49m\u001b[43m \u001b[49m\u001b[43mgids\u001b[49m\u001b[43m,\u001b[49m\u001b[43m \u001b[49m\u001b[43muid\u001b[49m\u001b[43m,\u001b[49m\u001b[43m \u001b[49m\u001b[43mumask\u001b[49m\u001b[43m,\u001b[49m\n\u001b[32m   1034\u001b[39m \u001b[43m                        \u001b[49m\u001b[43mstart_new_session\u001b[49m\u001b[43m,\u001b[49m\u001b[43m \u001b[49m\u001b[43mprocess_group\u001b[49m\u001b[43m)\u001b[49m\n\u001b[32m   1035\u001b[39m \u001b[38;5;28;01mexcept\u001b[39;00m:\n\u001b[32m   1036\u001b[39m     \u001b[38;5;66;03m# Cleanup if the child failed starting.\u001b[39;00m\n\u001b[32m   1037\u001b[39m     \u001b[38;5;28;01mfor\u001b[39;00m f \u001b[38;5;129;01min\u001b[39;00m \u001b[38;5;28mfilter\u001b[39m(\u001b[38;5;28;01mNone\u001b[39;00m, (\u001b[38;5;28mself\u001b[39m.stdin, \u001b[38;5;28mself\u001b[39m.stdout, \u001b[38;5;28mself\u001b[39m.stderr)):\n\n\u001b[36mFile \u001b[39m\u001b[32m/usr/lib/python3.12/subprocess.py:1955\u001b[39m, in \u001b[36mPopen._execute_child\u001b[39m\u001b[34m(self, args, executable, preexec_fn, close_fds, pass_fds, cwd, env, startupinfo, creationflags, shell, p2cread, p2cwrite, c2pread, c2pwrite, errread, errwrite, restore_signals, gid, gids, uid, umask, start_new_session, process_group)\u001b[39m\n\u001b[32m   1953\u001b[39m     err_msg = os.strerror(errno_num)\n\u001b[32m   1954\u001b[39m \u001b[38;5;28;01mif\u001b[39;00m err_filename \u001b[38;5;129;01mis\u001b[39;00m \u001b[38;5;129;01mnot\u001b[39;00m \u001b[38;5;28;01mNone\u001b[39;00m:\n\u001b[32m-> \u001b[39m\u001b[32m1955\u001b[39m     \u001b[38;5;28;01mraise\u001b[39;00m child_exception_type(errno_num, err_msg, err_filename)\n\u001b[32m   1956\u001b[39m \u001b[38;5;28;01melse\u001b[39;00m:\n\u001b[32m   1957\u001b[39m     \u001b[38;5;28;01mraise\u001b[39;00m child_exception_type(errno_num, err_msg)\n\n\u001b[31mFileNotFoundError\u001b[39m: [Errno 2] No such file or directory: 'netstat'\n"}}
    """.strip()

    text = json.dumps(text)
    print(text)

    count = count_tokens(text)
    print(f"Token 数: {count}")

    # # 使用示例
    # text = "Kimi K2.5 是一个开源的原生多模态智能体模型，在 Kimi-K2-Base 基础上通过约 15 万亿混合视觉与文本 token 的持续预训练构建而成。该模型无缝融合了视觉与语言理解能力，并具备高级智能体功能，支持即时模式与思考模式，以及对话式与智能体式交互范式。"
    # count, tokens = count_tokens_modelscope(text, "deepseek-ai/DeepSeek-V3.2")
    # print(f"Token 数: {count}")
    # print(f"Tokens: {tokens}")
    # count, tokens = count_tokens_modelscope(text, "Qwen/Qwen2.5-7B-Instruct")
    # print(f"Token 数: {count}")
    # print(f"Tokens: {tokens}")
    # count, tokens = count_tokens_modelscope(text, "moonshotai/Kimi-K2.5")
    # print(f"Token 数: {count}")
    # print(f"Tokens: {tokens}")