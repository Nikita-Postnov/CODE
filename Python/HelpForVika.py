def max_blocks(arr):
    if n == 0:
        return 0
    
    max_block_count = 0
    max_val = 0
    
    for i in range(n):
        max_val = max(max_val, arr[i])
        if max_val == i:
            max_block_count += 1
            
    return max_block_count

if __name__ == "__main__":
    n = int(input())
    arr = [int(x) for x in input().split()]
    result = max_blocks(arr)
    print(result)