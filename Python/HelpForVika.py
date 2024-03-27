def max_blocks_to_sort(data):
    n = len(data)
    max_blocks = 0
    current_block_size = 1
    for i in range(1, n):
        if data[i] == data[i - 1] + 1:
            current_block_size += 1
        else:
            max_blocks = max(max_blocks, current_block_size)
            current_block_size = 1
    max_blocks = max(max_blocks, current_block_size)
    return max_blocks

n = int(input())
data = list(map(int, input().split()))

print(max_blocks_to_sort(data))