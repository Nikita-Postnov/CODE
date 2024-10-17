import tkinter as tk
import time
from datetime import datetime
from babel.dates import format_datetime

# Функция для обновления времени и даты


def update_time():
    current_time = time.strftime("%H:%M:%S")
    # Используем babel для отображения даты на русском
    current_date = format_datetime(
        datetime.now(), "EEEE, d MMMM yyyy", locale='ru')

    time_label.config(text=current_time)
    date_label.config(text=current_date)

    # Обновляем каждые 1000 миллисекунд (1 секунда)
    root.after(1000, update_time)


# Создание основного окна приложения
root = tk.Tk()
root.title("Часы и дата")

# Настройка окна
root.geometry("400x200")
root.resizable(False, False)

# Создание меток для времени и даты
time_label = tk.Label(root, font=("Arial", 48), fg="black")
time_label.pack(pady=20)

date_label = tk.Label(root, font=("Arial", 24), fg="black")
date_label.pack(pady=10)

# Вызов функции для обновления времени
update_time()

# Запуск главного цикла Tkinter
root.mainloop()
