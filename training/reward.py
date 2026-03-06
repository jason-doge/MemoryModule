import math
import os
from typing import Dict, List, Any, Optional, Tuple, Union
from dataclasses import dataclass, field
from enum import Enum
import json
from pathlib import Path

# 需要安装: pip install openai
from openai import OpenAI


# ==================== 数据结构与枚举 ====================

class StepLabel(Enum):
    """步骤有效性标签"""
    EFFECTIVE = "effective"
    INEFFICIENT = "inefficient"


class BaseAction(Enum):
    """模型A的基础动作类型"""
    S1_SUMMARIZE_ADD = "S1_SUMMARIZE_ADD"
    S2_RAW_ADD = "S2_RAW_ADD"
    S3_UPDATE_REPLACE = "S3_UPDATE_REPLACE"
    S4_DISCARD = "S4_DISCARD"


@dataclass
class StepInfo:
    """步骤信息"""
    label: StepLabel
    action_type: Optional[BaseAction] = None


@dataclass
class MemoryBankState:
    """记忆库状态"""
    mem_count: int
    max_memories: int = 200


@dataclass
class SupportMetrics:
    """支持度指标 S1 和 S2"""
    S1: float  # 基于原始检索记忆（格式化后）的支持度
    S2: float  # 基于蒸馏记忆（三段式格式化后）的支持度


@dataclass
class JudgeProbs:
    """Judge模型输出的概率分布"""
    p_A: float
    p_B: float
    p_C: float

    def get_correct_prob(self, correct_option: str) -> float:
        """获取正确选项的概率"""
        return getattr(self, f"p_{correct_option}", 1e-10)

    def get_wrong_probs(self, correct_option: str) -> Tuple[float, float]:
        """获取两个错误选项的概率"""
        options = ['A', 'B', 'C']
        options.remove(correct_option)
        return getattr(self, f"p_{options[0]}", 1e-10), getattr(self, f"p_{options[1]}", 1e-10)


# ==================== 超参数配置 ====================

@dataclass
class StepWeightConfig:
    """步骤权重 w 的配置（可调超参数）"""
    effective: float = 1.0
    inefficient: float = 0.5


@dataclass
class JudgeConfig:
    """Judge模型配置"""
    model_name: str = "gpt-4o"
    temperature: float = 0.0
    max_tokens: int = 1
    top_logprobs: int = 5
    api_key: Optional[str] = None
    base_url: Optional[str] = None


@dataclass
class ModelAHyperParams:
    """模型A超参数"""
    lambda_1: float = 0.3
    lambda_2: float = 0.7
    lambda_g: float = 0.2
    beta_fmt: float = 0.1
    beta_bad: float = 0.5
    beta_size: float = 0.01
    M: int = 200
    step_weights: StepWeightConfig = field(default_factory=StepWeightConfig)


@dataclass
class ModelBHyperParams:
    """模型B超参数"""
    delta: float = 2.0
    alpha: float = 0.3
    tau: float = -0.2
    beta_fmt: float = 0.2
    beta_bad: float = 0.8
    step_weights: StepWeightConfig = field(default_factory=StepWeightConfig)


# ==================== Judge模型调用与支持度计算 ====================

class JudgeEvaluator:
    """
    Judge模型评估器
    用于计算 S1（基于原始检索记忆格式化内容）和 S2（基于蒸馏记忆格式化内容）的支持度
    """

    def __init__(self, model: Optional[str] = "qwen-max", config: Optional[JudgeConfig] = None):
        if config is not None:
            self.config = config
        else:
            llm_config_json = Path().cwd().resolve() / "llm_config.json"
            with open(llm_config_json, "r", encoding="utf-8") as f:
                cfg = json.load(f)
            cfg = cfg.get("judge", {}).get(model, {})
            self.config = JudgeConfig(
                model_name=cfg.get("model_name", "qwen3-max"),
                temperature=cfg.get("temperature", 0.0),
                max_tokens=cfg.get("max_tokens", 1),
                top_logprobs=cfg.get("top_logprobs", 5),
                api_key=cfg.get("api_key", None),
                base_url=cfg.get("base_url", None)
            )
        self.client = OpenAI(
            api_key=self.config.api_key or os.getenv("OPENAI_API_KEY", ""),
            base_url=self.config.base_url or os.getenv("OPENAI_BASE_URL", None)
        )
        self.judge_prompt_template = "{{INPUT_JSON}}"

    def format_prompt(
            self,
            overall_goal: str,
            obs_source_command: str,
            obs_text: str,
            formatted_memories: str,  # 可以是检索记忆格式化内容或蒸馏记忆格式化内容
            candidates: Dict[str, str]
    ) -> str:
        """
        格式化Judge提示词
        将格式化后的记忆内容填充到模板中
        """
        context = {
            "overall_goal": overall_goal,
            "obs": {
                "source_command": obs_source_command,
                "obs_text": obs_text
            },
            "formatted_memories": formatted_memories,  # 已格式化的记忆内容
            "candidates": candidates
        }

        # 使用模板字符串替换
        prompt = self.judge_prompt_template.replace("{{INPUT_JSON}}", json.dumps(context, indent=2))
        return prompt

    def get_token_probs(self, prompt: str) -> Optional[JudgeProbs]:
        """
        调用Judge模型获取A/B/C三个选项的概率分布

        Returns:
            JudgeProbs对象，包含p_A, p_B, p_C
        """
        try:
            response = self.client.chat.completions.create(
                model=self.config.model_name,
                messages=[{"role": "user", "content": prompt}],
                temperature=self.config.temperature,
                max_tokens=self.config.max_tokens,
                logprobs=True,
                top_logprobs=self.config.top_logprobs
            )

            if not response.choices[0].logprobs or not response.choices[0].logprobs.content:
                return None

            token_info = response.choices[0].logprobs.content[0]
            top_logprobs = token_info.top_logprobs

            # 初始化概率（使用极小值避免log(0)）
            probs = {'A': 1e-10, 'B': 1e-10, 'C': 1e-10}

            # 从top_logprobs中提取A/B/C的概率
            for item in top_logprobs:
                token = item.token.strip()
                if token in probs:
                    probs[token] = math.exp(item.logprob)

            # 归一化概率
            total = probs['A'] + probs['B'] + probs['C']
            if total > 0:
                probs['A'] /= total
                probs['B'] /= total
                probs['C'] /= total

            return JudgeProbs(
                p_A=probs['A'],
                p_B=probs['B'],
                p_C=probs['C']
            )

        except Exception as e:
            print(f"Error calling Judge API: {e}")
            return None

    def calculate_support_score(self, probs: JudgeProbs, correct_option: str) -> float:
        """
        计算支持度 S = log(p_correct) - log(p_wrong1 + p_wrong2)
        """
        p_correct = probs.get_correct_prob(correct_option)
        p_wrong1, p_wrong2 = probs.get_wrong_probs(correct_option)

        p_correct = max(p_correct, 1e-10)
        p_wrong_sum = max(p_wrong1 + p_wrong2, 1e-10)

        return math.log(p_correct) - math.log(p_wrong_sum)

    def evaluate(
            self,
            correct_option: str,
            overall_goal: str,
            obs_source_command: str,
            obs_text: str,
            retrieved_memories_formatted: str,  # ③ 检索记忆格式化内容（用于S1）
            distilled_memories_formatted: str,  # ④ 蒸馏记忆格式化内容（用于S2）
            candidates: Dict[str, str]
    ) -> SupportMetrics:
        """
        同时计算S1和S2的支持度

        S1: 使用检索记忆（经过通用模型格式化，但未整理为三段式）
        S2: 使用蒸馏记忆（经过通用模型整理为三段式）
        """
        # 计算S2：使用蒸馏记忆（三段式格式化）
        prompt_s2 = self.format_prompt(
            overall_goal=overall_goal,
            obs_source_command=obs_source_command,
            obs_text=obs_text,
            formatted_memories=distilled_memories_formatted,
            candidates=candidates
        )

        probs_s2 = self.get_token_probs(prompt_s2)
        S2 = self.calculate_support_score(probs_s2, correct_option) if probs_s2 else 0.0

        # 计算S1：使用检索记忆（格式化但未三段式整理）
        prompt_s1 = self.format_prompt(
            overall_goal=overall_goal,
            obs_source_command=obs_source_command,
            obs_text=obs_text,
            formatted_memories=retrieved_memories_formatted,
            candidates=candidates
        )

        probs_s1 = self.get_token_probs(prompt_s1)
        S1 = self.calculate_support_score(probs_s1, correct_option) if probs_s1 else 0.0

        return SupportMetrics(S1=S1, S2=S2)


# ==================== 格式验证工具函数 ====================

def validate_json_format(output_text: str) -> bool:
    """验证JSON格式有效性"""
    try:
        json.loads(output_text)
        return True
    except:
        return False


def validate_schema_compliance_model_a(output_data: Dict[str, Any]) -> Tuple[bool, List[str]]:
    """
    验证模型A输出Schema合规性
    检查：decisions数组、base_action合法性、S3约束、S4约束、mark_key约束等
    """
    violations = []

    if "decisions" not in output_data:
        violations.append("缺少decisions字段")
        return True, violations

    decisions = output_data.get("decisions", [])
    if not decisions:
        violations.append("decisions数组为空")

    for decision in decisions:
        # 检查必要字段
        if "base_action" not in decision:
            violations.append("decision缺少base_action")
            continue

        action = decision.get("base_action")
        if action not in [e.value for e in BaseAction]:
            violations.append(f"非法base_action: {action}")
            continue

        # S3_UPDATE_REPLACE特定约束
        if action == BaseAction.S3_UPDATE_REPLACE.value:
            s3_update = decision.get("s3_update", [])
            if not s3_update:
                violations.append("S3_UPDATE_REPLACE但s3_update为空")
            if len(s3_update) > 3:
                violations.append("S3_UPDATE_REPLACE但s3_update超过3个条目")

        # S4_DISCARD特定约束
        if action == BaseAction.S4_DISCARD.value:
            if len(decisions) != 1:
                violations.append("S4_DISCARD时decisions数量只能为1")
            if decision.get("mark_key") is not False:
                violations.append("S4_DISCARD时mark_key必须为false")
            if decision.get("key_type") is not None:
                violations.append("S4_DISCARD时key_type必须为null")
            if decision.get("key_level") != 0:
                violations.append("S4_DISCARD时key_level必须为0")

        # mark_key约束
        if decision.get("mark_key"):
            if not decision.get("key_type"):
                violations.append("mark_key=true时key_type必须非空")
            if decision.get("key_level") not in [1, 2]:
                violations.append("mark_key=true时key_level必须在[1,2]")
        else:
            if decision.get("key_type") is not None:
                violations.append("mark_key=false时key_type必须为null")
            if decision.get("key_level") != 0:
                violations.append("mark_key=false时key_level必须为0")

        # reason约束
        if not decision.get("reason"):
            violations.append("reason不能为空")

    return len(violations) > 0, violations


def validate_schema_compliance_model_b(output_data: Dict[str, Any]) -> Tuple[bool, List[str]]:
    """
    验证模型B输出Schema合规性

    注意：不检查"三段式摘要缺段"，因为记忆格式化由冻结参数的通用模型完成，
    不属于模型B的训练范围。只检查B模型自身的输出格式。

    检查项：
    1. 是否存在memories数组
    2. 每个条目是否有mem_id, selected, reason
    3. 是否有多余字段
    4. selected是否为boolean类型
    """
    violations = []

    if "memories" not in output_data:
        violations.append("缺少memories字段")
        return True, violations

    memories = output_data.get("memories", [])
    if not memories:
        violations.append("memories数组为空")

    allowed_fields = {"mem_id", "selected", "reason"}

    for mem in memories:
        # 检查必要字段
        if "mem_id" not in mem:
            violations.append("记忆条目缺少mem_id")
        if "selected" not in mem:
            violations.append("记忆条目缺少selected字段")
        if "reason" not in mem:
            violations.append("记忆条目缺少reason字段")

        # 检查多余字段
        extra_fields = set(mem.keys()) - allowed_fields
        if extra_fields:
            violations.append(f"记忆条目包含多余字段: {extra_fields}")

        # 检查selected类型
        if "selected" in mem and not isinstance(mem["selected"], bool):
            violations.append("selected字段必须是boolean类型")

    return len(violations) > 0, violations


def get_step_weight(step_label: StepLabel, config: StepWeightConfig) -> float:
    """获取步骤权重 w"""
    return config.effective if step_label == StepLabel.EFFECTIVE else config.inefficient


def clamp(x: float, min_val: float, max_val: float) -> float:
    """限幅函数"""
    return max(min_val, min(max_val, x))


# ==================== 模型A奖励函数 ====================

class ModelAReward:
    """模型A奖励函数实现（记忆管理决策器）"""

    def __init__(self, hyperparams: Optional[ModelAHyperParams] = None):
        self.hp = hyperparams or ModelAHyperParams()

    def compute_effective_reward(self, step_info: StepInfo, support_metrics: SupportMetrics) -> float:
        """
        R_A_effective = w * [lambda_1 * S1 + lambda_2 * S2 + lambda_g * (S2 - S1)]
        """
        w = get_step_weight(step_info.label, self.hp.step_weights)
        S1, S2 = support_metrics.S1, support_metrics.S2

        distillation_gain = S2 - S1

        reward = w * (
                self.hp.lambda_1 * S1 +
                self.hp.lambda_2 * S2 +
                self.hp.lambda_g * distillation_gain
        )

        return reward

    def compute_format_reward(self, model_output: str, parsed_output: Dict[str, Any]) -> float:
        """
        R_A_format = beta_fmt * I(json_valid) - beta_bad * I(schema_violate)
        """
        is_json_valid = validate_json_format(model_output)
        is_schema_violation, _ = validate_schema_compliance_model_a(parsed_output)

        reward = (
                self.hp.beta_fmt * (1.0 if is_json_valid else 0.0) -
                self.hp.beta_bad * (1.0 if is_schema_violation else 0.0)
        )

        return reward

    def compute_bank_health_reward(self, memory_bank: MemoryBankState) -> float:
        """
        R_bank_health = -beta_size * max(0, mem_count - M)
        """
        excess = max(0, memory_bank.mem_count - self.hp.M)
        return -self.hp.beta_size * excess

    def compute_total_reward(
            self,
            step_info: StepInfo,
            support_metrics: SupportMetrics,
            model_output: str,  # ① A模型的输出（JSON字符串）
            parsed_output: Dict[str, Any],
            memory_bank: MemoryBankState
    ) -> Dict[str, float]:
        """计算总奖励 R_A"""
        r_effective = self.compute_effective_reward(step_info, support_metrics)
        r_format = self.compute_format_reward(model_output, parsed_output)
        r_health = self.compute_bank_health_reward(memory_bank)

        total = r_effective + r_format + r_health

        return {
            "R_A_total": total,
            "R_A_effective": r_effective,
            "R_A_format": r_format,
            "R_bank_health": r_health,
            "step_weight": get_step_weight(step_info.label, self.hp.step_weights),
            "distillation_gain": support_metrics.S2 - support_metrics.S1
        }


# ==================== 模型B奖励函数 ====================

class ModelBReward:
    """模型B奖励函数实现（记忆选择器）"""

    def __init__(self, hyperparams: Optional[ModelBHyperParams] = None):
        self.hp = hyperparams or ModelBHyperParams()

    def compute_effective_reward(self, step_info: StepInfo, support_metrics: SupportMetrics) -> float:
        """
        R_B_effective = w * clamp(S2 - S1, -delta, +delta) + w * alpha * max(0, S2 - tau)

        注意：S2-S1表示记忆选择（B模型动作）对蒸馏质量的提升
        """
        w = get_step_weight(step_info.label, self.hp.step_weights)
        S1, S2 = support_metrics.S1, support_metrics.S2

        # 差分项（截断）
        diff = S2 - S1
        clamped_diff = clamp(diff, -self.hp.delta, self.hp.delta)
        differential_term = w * clamped_diff

        # 绝对质量项
        absolute_quality = max(0, S2 - self.hp.tau)
        absolute_term = w * self.hp.alpha * absolute_quality

        return differential_term + absolute_term

    def compute_format_reward(self, model_output: str, parsed_output: Dict[str, Any]) -> float:
        """
        R_B_format = beta_fmt * I(json_valid) - beta_bad * I(schema_violate)

        注意：不检查三段式摘要缺段，因为那是下游冻结通用模型的责任
        """
        is_json_valid = validate_json_format(model_output)
        is_schema_violation, _ = validate_schema_compliance_model_b(parsed_output)

        reward = (
                self.hp.beta_fmt * (1.0 if is_json_valid else 0.0) -
                self.hp.beta_bad * (1.0 if is_schema_violation else 0.0)
        )

        return reward

    def compute_total_reward(
            self,
            step_info: StepInfo,
            support_metrics: SupportMetrics,
            model_output: str,  # ② B模型的输出（JSON字符串）
            parsed_output: Dict[str, Any]
    ) -> Dict[str, float]:
        """计算总奖励 R_B"""
        r_effective = self.compute_effective_reward(step_info, support_metrics)
        r_format = self.compute_format_reward(model_output, parsed_output)

        total = r_effective + r_format

        return {
            "R_B_total": total,
            "R_B_effective": r_effective,
            "R_B_format": r_format,
            "step_weight": get_step_weight(step_info.label, self.hp.step_weights),
            "S2_minus_S1": support_metrics.S2 - support_metrics.S1,
            "S2_clamped": clamp(support_metrics.S2 - support_metrics.S1,
                                -self.hp.delta, self.hp.delta)
        }


# ==================== 使用示例 ====================

def example_usage():
    """完整使用示例 - Web渗透测试场景：SQL注入发现与利用决策"""

    # ==================== 1. 初始化配置 ====================
    judge_config = JudgeConfig(
        model_name="gpt-4o",
        temperature=0.0,
        max_tokens=1,
        top_logprobs=5,
        api_key=os.getenv("OPENAI_API_KEY"),
        base_url=os.getenv("OPENAI_BASE_URL")
    )

    judge = JudgeEvaluator(config=judge_config)
    judge.judge_prompt_template = "{{JUDGE_PROMPT_TEMPLATE}}"

    # ==================== 2. 渗透测试上下文 ====================
    overall_goal = "获取目标主机10.0.0.5的初始代码执行权限"
    obs_source_command = "sqlmap -u 'http://10.0.0.5/product.php?id=1' --batch"
    obs_text = """
    sqlmap identified the following injection point:
    Parameter: id (GET)
    Type: Union Query
    Title: MySQL Union query (NULL) - 3 columns
    Payload: id=1' UNION ALL SELECT NULL,NULL,CONCAT(0x717a7a7171,0x6473626...)
    [INFO] the back-end DBMS is MySQL
    web server operating system: Linux Ubuntu 20.04
    web application technology: Apache 2.4.41, PHP 7.4.3
    back-end DBMS: MySQL >= 5.0.12
    """

    candidates = {
        "A": "继续探测id参数的其他注入类型（时间盲注、报错注入），收集更多漏洞变体证据后再尝试利用",
        "B": "直接利用当前确认的Union注入点提取数据库版本信息，然后尝试读取/etc/passwd文件验证权限",
        "C": "放弃当前注入点，转而扫描其他未测试的URL参数（如category、page等）"
    }
    correct_option = "B"

    # ==================== 3. 模型A输出（记忆管理决策器） ====================
    model_a_output = json.dumps({
        "decisions": [
            {
                "base_action": "S1_SUMMARIZE_ADD",
                "s3_update": [],
                "mark_key": True,
                "key_type": "INJECTION_POINT",
                "key_level": 2,
                "reason": "SQLMap confirmed Union injection with MySQL backend. High-confidence exploitability, suitable for immediate use."
            }
        ]
    })
    model_a_parsed = json.loads(model_a_output)

    # ==================== 4. 模型B输出（记忆选择器） ====================
    model_b_output = json.dumps({
        "memories": [
            {
                "mem_id": "mem_001_sqlmap",
                "selected": True,
                "reason": "Directly contains confirmed SQL injection technical details and payload."
            },
            {
                "mem_id": "mem_003_nmap",
                "selected": True,
                "reason": "Provides OS and service context useful for post-exploitation."
            },
            {
                "mem_id": "mem_002_ssh",
                "selected": False,
                "reason": "SSH port information not relevant to current web injection subgoal."
            },
            {
                "mem_id": "mem_004_fail_login",
                "selected": False,
                "reason": "Failed login attempt noise, not relevant to injection vector."
            },
            {
                "mem_id": "mem_005_css",
                "selected": False,
                "reason": "CSS file discovery from dirb scan, low relevance to current task."
            }
        ]
    })
    model_b_parsed = json.loads(model_b_output)

    # ==================== 5. 记忆格式化内容（均为三段式JSON格式） ====================

    # ③ 检索记忆格式化内容（S1）：
    # 使用从记忆库检索的原始记忆（包含噪声：SSH、失败登录、CSS文件等）
    # 由通用模型格式化为三段式，但包含较多无关信息
    retrieved_memories_formatted = json.dumps({
        "distilled_summary": {
            "recent_progress": [
                "SQLMap scan completed on product.php id parameter confirmed Union injection vulnerability.",
                "Multiple noisy entries in memory bank include unrelated SSH scans and failed login attempts.",
                "Current injection point details mixed with enumeration noise from previous dirb scan."
            ],
            "prior_related_attempts": [
                "Previous SQLMap attempt on id parameter documented but buried under other memory entries.",
                "Nmap scan showing MySQL port 3306 open noted in mem_003.",
                "Multiple irrelevant entries concerning CSS files and static resources clutter the context.",
                "Failed login attempt on admin panel recorded but not useful for current injection approach."
            ],
            "unexplored_entry_points": [
                "[MEDIUM] MySQL injection confirmed but specific exploitation path unclear due to memory noise.",
                "[LOW] SSH port 22 open: mentioned in scan results but not directly relevant to web app.",
                "[LOW] Admin login page discovered: previously attempted with no success, may revisit later.",
                "[LOW] CSS and static resource enumeration results present but not actionable for injection."
            ]
        }
    }, ensure_ascii=False)

    # ④ 蒸馏记忆格式化内容（S2）：
    # 使用B模型筛选后的记忆（仅mem_001_sqlmap和mem_003_nmap，排除了噪声）
    # 由通用模型格式化为三段式，内容更精炼、聚焦
    distilled_memories_formatted = json.dumps({
        "distilled_summary": {
            "recent_progress": [
                "Successfully confirmed Union-based SQL injection on product.php id parameter using SQLMap.",
                "Injection specifics: MySQL backend, 3 columns, payload structure identified.",
                "Target environment: Ubuntu 20.04, Apache 2.4.41, PHP 7.4.3, MySQL 8.0.27 confirmed."
            ],
            "prior_related_attempts": [
                "Initial parameter discovery via ffuf directory enumeration identified id as potential target.",
                "Previous authentication attempts abandoned in favor of confirmed injection vector.",
                "Database service on 3306/tcp correlated with web application backend for potential lateral movement."
            ],
            "unexplored_entry_points": [
                "[HIGH] Direct exploitation via Union injection: ready to extract version info and test file read capabilities (LOAD_FILE).",
                "[MEDIUM] MySQL 3306/tcp: potential for direct connection if web-based extraction limited.",
                "[MEDIUM] Apache/PHP stack: additional endpoints may exist beyond product.php for expanded attack surface.",
                "[LOW] Local file inclusion via SQL injection: /etc/passwd, application source code accessible via SQL."
            ]
        }
    }, ensure_ascii=False)

    # ==================== 6. 计算支持度 ====================
    print("=== Judge模型评估支持度 ===")

    support_metrics = judge.evaluate(
        correct_option=correct_option,
        overall_goal=overall_goal,
        obs_source_command=obs_source_command,
        obs_text=obs_text,
        retrieved_memories_formatted=retrieved_memories_formatted,  # S1：原始检索记忆的格式化结果
        distilled_memories_formatted=distilled_memories_formatted,  # S2：筛选后记忆的格式化结果
        candidates=candidates
    )

    print(f"S1 (原始检索记忆格式化): {support_metrics.S1:.4f}")
    print(f"S2 (筛选后蒸馏记忆格式化): {support_metrics.S2:.4f}")
    print(f"差值 (S2-S1): {support_metrics.S2 - support_metrics.S1:.4f}")
    print(f"说明: B模型的筛选动作将支持度提升了 {support_metrics.S2 - support_metrics.S1:.4f}")

    # ==================== 7. 模型A奖励计算 ====================
    print("\n=== 模型A奖励计算 ===")

    step_info = StepInfo(label=StepLabel.EFFECTIVE, action_type=BaseAction.S1_SUMMARIZE_ADD)
    memory_bank = MemoryBankState(mem_count=185, max_memories=200)

    reward_a = ModelAReward().compute_total_reward(
        step_info=step_info,
        support_metrics=support_metrics,
        model_output=model_a_output,
        parsed_output=model_a_parsed,
        memory_bank=memory_bank
    )

    print(f"步骤权重 w: {reward_a['step_weight']:.1f}")
    print(f"主效用项: {reward_a['R_A_effective']:.4f} (含λ_g*蒸馏增益)")
    print(f"格式奖励: {reward_a['R_A_format']:.4f}")
    print(f"健康惩罚: {reward_a['R_bank_health']:.4f}")
    print(f"总奖励: {reward_a['R_A_total']:.4f}")

    # ==================== 8. 模型B奖励计算 ====================
    print("\n=== 模型B奖励计算 ===")

    reward_b = ModelBReward().compute_total_reward(
        step_info=step_info,
        support_metrics=support_metrics,
        model_output=model_b_output,
        parsed_output=model_b_parsed
    )

    print(f"步骤权重 w: {reward_b['step_weight']:.1f}")
    print(f"限幅差分项: {reward_b['S2_clamped']:.4f} (原始差值: {reward_b['S2_minus_S1']:.4f})")
    print(f"绝对质量项: {max(0, support_metrics.S2 - (-0.2)):.4f}")
    print(f"主效用项: {reward_b['R_B_effective']:.4f}")
    print(f"格式奖励: {reward_b['R_B_format']:.4f}")
    print(f"总奖励: {reward_b['R_B_total']:.4f}")

    # ==================== 9. 总结 ====================
    print("\n=== 数据流逻辑 ===")
    print("1. 从记忆库检索得到5条记忆（含噪声）")
    print("2. A模型决定：S1_SUMMARIZE_ADD保存SQLMap结果并标记关键")
    print("3. B模型筛选：从5条中选出2条相关（SQL注入+主机信息），排除3条噪声")
    print("4. 通用模型格式化（相同提示词）:")
    print("   - 输入原始5条 → 生成S1三段式（含噪声，质量较低）")
    print("   - 输入筛选2条 → 生成S2三段式（精炼，质量较高）")
    print(f"5. Judge评估：S2({support_metrics.S2:.3f}) > S1({support_metrics.S1:.3f})")
    print("6. 奖励反映：B模型的筛选有效提升了规划支持度")


if __name__ == "__main__":
    example_usage()