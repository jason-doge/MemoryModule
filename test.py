def slice_by_threshold(numbers, threshold):
    """
    将列表从左到右划分为多个切片，每个切片的和不大于 threshold。
    如果单个数字大于 threshold，则它自己成为一个组。

    Args:
        numbers: 数字列表
        threshold: 阈值

    Returns:
        切片列表，每个切片是一个子列表
    """
    if not numbers:
        return []

    slices = []
    current_slice = []
    current_sum = 0

    for num in numbers:
        if num > threshold:
            # 如果当前切片非空，先保存当前累积的切片
            if current_slice:
                slices.append(current_slice)
                current_slice = []
                current_sum = 0

            # 该数字单独成为一个组
            slices.append([num])
        else:
            # 正常情况：检查加入后是否会超过阈值
            if current_sum + num > threshold:
                # 保存当前切片，开启新切片
                slices.append(current_slice)
                current_slice = [num]
                current_sum = num
            else:
                # 加入当前切片
                current_slice.append(num)
                current_sum += num

    # 别忘了最后一个切片
    if current_slice:
        slices.append(current_slice)

    return slices


# ============ 测试 ============

# 测试 1：包含超大数字
numbers = [1, 2, 8, 3, 4, 20, 5, 6]
threshold = 10
result = slice_by_threshold(numbers, threshold)
print(f"原列表: {numbers}")
print(f"阈值: {threshold}")
print(f"划分结果: {result}")
# 输出: [[1, 2], [8], [3, 4], [20], [5, 6]]
# 解释: 
# - 1+2=3≤10, 3+8=11>10, 所以 [1,2] 保存，8 单独（因为 8≤10，但 3+8>10）
# - 等等，这里 8≤10，应该继续检查 8+3=11>10，所以 [8] 保存
# - 3+4=7≤10, 7+20>10，所以 [3,4] 保存
# - 20>10，单独成组 [20]
# - 5+6=11>10，所以 [5]，然后 [6]

# 修正我的手动计算：
# 1: sum=0+1=1, slice=[1]
# 2: sum=1+2=3, slice=[1,2]
# 8: 3+8=11>10，保存 [1,2]，新 slice=[8]，sum=8
# 3: 8+3=11>10，保存 [8]，新 slice=[3]，sum=3
# 4: 3+4=7≤10，slice=[3,4]，sum=7
# 20: 20>10，保存 [3,4]，单独 [20]
# 5: slice=[5]，sum=5
# 6: 5+6=11>10，保存 [5]，新 slice=[6]
# 最终结果: [[1,2], [8], [3,4], [20], [5], [6]]

print(f"各组和: {[sum(s) for s in result]}")

# 测试 2：正常情况（没有超大数字）
print(f"\n正常情况: {slice_by_threshold([1, 2, 3, 4, 5], 5)}")
# [[1,2], [3], [4], [5]]

# 测试 3：所有数字都超大
print(f"全超大: {slice_by_threshold([100, 200, 50], 10)}")
# [[100], [200], [50]]