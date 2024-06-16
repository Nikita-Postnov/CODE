import tkinter as tk
from datetime import datetime


class Clock(tk.Frame):
    def __init__(self, master=None):
        super().__init__(master)
        self.master = master
        self.pack()
        self.create_widgets()

    def create_widgets(self):
        self.time_label = tk.Label(self, font=('Arial', 24), fg='blue')
        self.time_label.pack()
        self.update_time()

    def update_time(self):
        now = datetime.now().strftime("%H:%M:%S")
        self.time_label.config(text=now)
        self.after(1000, self.update_time)


root = tk.Tk()
root.title("Часы")
root.geometry("200x50")
root.resizable(False, False)

clock = Clock(root)
clock.mainloop()
