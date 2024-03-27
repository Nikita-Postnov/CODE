def max_blocks_to_sort(array):
    n = len(array)
    if n == 0:
        return 0
    
    sorted_array = sorted(array)
    max_blocks = 1
    curr_max = 0
    
    for i in range(n):
        curr_max = max(curr_max, array[i])
        if curr_max == i:
            max_blocks += 1
    
    return max_blocks

data = [3, 1, 0, 2, 6, 5, 4, 7]
print("Максимальное количество блоков для частичной сортировки:", max_blocks_to_sort(data))
