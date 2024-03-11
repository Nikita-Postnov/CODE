import random
import tkinter as tk
from tkinter import messagebox

class RockPaperScissorsGame:
    def __init__(self):
        self.root = tk.Tk()
        self.root.title("Камень, ножницы, бумага")

        self.choices = ["камень", "ножницы", "бумага"]

        self.label = tk.Label(self.root, text="Выберите: камень, ножницы или бумага", font=("Arial", 12))
        self.label.pack(pady=10)

        self.buttons = []
        for choice in self.choices:
            button = tk.Button(self.root, text=choice, command=lambda c=choice: self.check_result(c))
            button.pack(pady=5)
            self.buttons.append(button)

        self.root.mainloop()

    def check_result(self, user_choice):
        computer_choice = random.choice(self.choices)
        if user_choice == computer_choice:
            messagebox.showinfo("Результат", f"Ничья! Оба выбрали {user_choice}")
        elif (user_choice == "камень" and computer_choice == "ножницы") or (user_choice == "ножницы" and computer_choice == "бумага") or (user_choice == "бумага" and computer_choice == "камень"):
            messagebox.showinfo("Победа", f"Поздравляем! Вы выбрали {user_choice}, компьютер выбрал {computer_choice}. Вы победили!")
        else:
            messagebox.showinfo("Поражение", f"К сожалению, компьютер выбрал {computer_choice} и победил вас")

if __name__ == "__main__":
    game = RockPaperScissorsGame()