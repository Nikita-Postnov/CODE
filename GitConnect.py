import tkinter as tk
from tkinter import messagebox

class TicTacToe:
    def __init__(self):
        self.root = tk.Tk()
        self.root.title("Крестики-нолики")

        self.current_player = "X"
        self.board = [" " for _ in range(9)]

        self.buttons = []
        for i in range(3):
            row = []
            for j in range(3):
                button = tk.Button(self.root, text=" ", font=("Arial", 20), width=5, height=2,
                                   command=lambda i=i, j=j: self.on_click(i, j))
                button.grid(row=i, column=j, sticky="nsew")
                row.append(button)
            self.buttons.append(row)

        self.root.mainloop()

    def on_click(self, i, j):
        if self.board[i * 3 + j] == " ":
            self.board[i * 3 + j] = self.current_player
            self.buttons[i][j].config(text=self.current_player)
            if self.check_winner():
                messagebox.showinfo("Победа", f"Игрок {self.current_player} победил!")
                self.root.quit()
            elif " " not in self.board:
                messagebox.showinfo("Ничья", "Ничья!")
                self.root.quit()
            else:
                self.current_player = "O" if self.current_player == "X" else "X"

    def check_winner(self):
        lines = [(0, 1, 2), (3, 4, 5), (6, 7, 8), (0, 3, 6), (1, 4, 7), (2, 5, 8), (0, 4, 8), (2, 4, 6)]
        for line in lines:
            if self.board[line[0]] == self.board[line[1]] == self.board[line[2]] != " ":
                return True
        return False

if __name__ == "__main__":
    game = TicTacToe()