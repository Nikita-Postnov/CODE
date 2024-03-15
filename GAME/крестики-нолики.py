# Пример игры "Крестики-нолики" против компьютера на Python с использованием библиотеки tkinter для графического интерфейса

import tkinter as tk
import random

def check_winner(board, player):
    for row in board:
        if all(cell == player for cell in row):
            return True

    for col in range(3):
        if all(board[row][col] == player for row in range(3)):
            return True

    if all(board[i][i] == player for i in range(3)) or all(board[i][2-i] == player for i in range(3)):
        return True

    return False

def get_empty_cells(board):
    return [(i, j) for i in range(3) for j in range(3) if board[i][j] == " "]

def make_computer_move(board):
    empty_cells = get_empty_cells(board)
    return random.choice(empty_cells)

class TicTacToe:
    def __init__(self, root):
        self.root = root
        self.root.title("Tic-Tac-Toe")
        self.board = [[" " for _ in range(3)] for _ in range(3)]
        self.create_ui()
        self.player = "X"

    def create_ui(self):
        self.buttons = []
        for i in range(3):
            row = []
            for j in range(3):
                btn = tk.Button(self.root, text="", width=10, height=3, command=lambda i=i, j=j: self.make_move(i, j))
                btn.grid(row=i, column=j)
                row.append(btn)
            self.buttons.append(row)

    def make_move(self, i, j):
        if self.board[i][j] == " ":
            self.board[i][j] = self.player
            self.buttons[i][j].config(text=self.player)
            if check_winner(self.board, self.player):
                tk.messagebox.showinfo("Winner", f"Player {self.player} wins!")
                self.reset_game()
            elif all(all(cell != " " for cell in row) for row in self.board):
                tk.messagebox.showinfo("Tie", "It's a tie!")
                self.reset_game()
            else:
                self.player = "X" if self.player == "O" else "O"
                if self.player == "O":
                    row, col = make_computer_move(self.board)
                    self.board[row][col] = self.player
                    self.buttons[row][col].config(text=self.player)
                    if check_winner(self.board, self.player):
                        tk.messagebox.showinfo("Winner", f"Player {self.player} wins!")
                        self.reset_game()
                    elif all(all(cell != " " for cell in row) for row in self.board):
                        tk.messagebox.showinfo("Tie", "It's a tie!")
                        self.reset_game()
                    else:
                        self.player = "X"

    def reset_game(self):
        self.board = [[" " for _ in range(3)] for _ in range(3)]
        for i in range(3):
            for j in range(3):
                self.buttons[i][j].config(text="")
        self.player = "X"

root = tk.Tk()
game = TicTacToe(root)
root.mainloop()