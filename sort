import random
import time

def quicksort(arr):
    if len(arr) <= 1:
        return arr
    else:
        pivot = arr[0]
        less = [x for x in arr[1:] if x <= pivot]
        greater = [x for x in arr[1:] if x > pivot]
        return quicksort(less) + [pivot] + quicksort(greater)

min_value = 0
max_value = 10000
num_elements = 10000

my_array = [random.randint(min_value, max_value) for _ in range(num_elements)]

start_time = time.time()

sorted_array = quicksort(my_array)

end_time = time.time()
sorting_time = end_time - start_time

print("Время сортировки QuickSort:", sorting_time)

def selection_sort(arr):
    for i in range(len(arr)):
        min_index = i
        for j in range(i+1, len(arr)):
            if arr[j] < arr[min_index]:
                min_index = j
        arr[i], arr[min_index] = arr[min_index], arr[i]
    return arr


my_array = [random.randint(min_value, max_value) for _ in range(num_elements)]


start_time = time.time()

sorted_array = selection_sort(my_array)

end_time = time.time()
sorting_time = end_time - start_time

print("Время сортировки SelectionSort:", sorting_time)

import random
import time

def merge_sort(arr):
    if len(arr) <= 1:
        return arr
    mid = len(arr) // 2
    left_half = arr[:mid]
    right_half = arr[mid:]
    left_half = merge_sort(left_half)
    right_half = merge_sort(right_half)
    return merge(left_half, right_half)

def merge(left, right):
    merged = []
    i = j = 0
    while i < len(left) and j < len(right):
        if left[i] < right[j]:
            merged.append(left[i])
            i += 1
        else:
            merged.append(right[j])
            j += 1
    while i < len(left):
        merged.append(left[i])
        i += 1
    while j < len(right):
        merged.append(right[j])
        j += 1
    return merged


my_array = [random.randint(min_value, max_value) for _ in range(num_elements)]

start_time = time.time()

sorted_array = merge_sort(my_array)

end_time = time.time()
sorting_time = end_time - start_time

print("Время сортировки MergeSort:", sorting_time)