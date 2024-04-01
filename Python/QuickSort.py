def quicksort(arr):
    if len(arr) <= 1:
        return arr
    pivot = arr[len(arr) // 2]
    left = [x for x in arr if x < pivot]
    middle = [x for x in arr if x == pivot]
    right = [x for x in arr if x > pivot]
    return quicksort(left) + middle + quicksort(right)

# Test the function
arr = [3, 1, 7, 9, 2, 5, 4, 6, 8]
sorted_arr = quicksort(arr)
print(sorted_arr)