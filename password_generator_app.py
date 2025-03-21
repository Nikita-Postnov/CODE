import tkinter as tk
from tkinter import ttk, messagebox, simpledialog
from password_manager import PasswordManager
from password_generator import PasswordGenerator

class PasswordGeneratorApp:
    def __init__(self, master):
        self.master = master
        master.title("Генератор паролей")
        master.geometry("500x600")
        master.minsize(500, 600)

        self.password_manager = PasswordManager()
        self.password_generator = PasswordGenerator()

        self.setup_styles()
        self.create_tabs()
        self.setup_keyboard_shortcuts()

    def setup_styles(self):
        style = ttk.Style()
        style.theme_use("clam")
        style.configure('TButton', font=('Arial', 10))
        style.configure('TLabel', font=('Arial', 10))
        style.configure('TEntry', font=('Arial', 10))
        style.configure('TCheckbutton', font=('Arial', 10))
        style.configure("red.Horizontal.TProgressbar", background='red')
        style.configure("yellow.Horizontal.TProgressbar", background='yellow')
        style.configure("green.Horizontal.TProgressbar", background='green')

    def create_tabs(self):
        self.tab_control = ttk.Notebook(self.master)
        self.generator_tab = ttk.Frame(self.tab_control)
        self.tab_control.add(self.generator_tab, text="Генератор")
        self.setup_generator_tab()
        self.manager_tab = ttk.Frame(self.tab_control)
        self.tab_control.add(self.manager_tab, text="Менеджер паролей")
        self.setup_manager_tab()
        self.tab_control.pack(expand=1, fill="both")

    def setup_generator_tab(self):
        frame = ttk.LabelFrame(self.generator_tab, text="Настройки генератора", padding=10)
        frame.pack(padx=10, pady=10, fill=tk.BOTH)
        ttk.Label(frame, text="Длина пароля:").grid(row=0, column=0, sticky=tk.W, pady=5)
        self.length_var = tk.IntVar(value=self.password_generator.password_length)
        length_entry = ttk.Entry(frame, textvariable=self.length_var, width=5)
        length_entry.grid(row=0, column=1, sticky=tk.W, pady=5)
        self.length_slider = ttk.Scale(frame, from_=4, to=32, orient=tk.HORIZONTAL, variable=self.length_var, length=200, command=self.update_length)
        self.length_slider.grid(row=0, column=2, sticky=tk.W, pady=5, padx=10)
        self.use_uppercase = tk.BooleanVar(value=self.password_generator.use_uppercase)
        ttk.Checkbutton(frame, text="Заглавные буквы (A-Z)", variable=self.use_uppercase).grid(row=1, column=0, columnspan=3, sticky=tk.W)
        self.use_lowercase = tk.BooleanVar(value=self.password_generator.use_lowercase)
        ttk.Checkbutton(frame, text="Строчные буквы (a-z)", variable=self.use_lowercase).grid(row=2, column=0, columnspan=3, sticky=tk.W)
        self.use_digits = tk.BooleanVar(value=self.password_generator.use_digits)
        ttk.Checkbutton(frame, text="Цифры (0-9)", variable=self.use_digits).grid(row=3, column=0, columnspan=3, sticky=tk.W)
        self.use_symbols = tk.BooleanVar(value=self.password_generator.use_symbols)
        ttk.Checkbutton(frame, text="Специальные символы (!@#$%)", variable=self.use_symbols).grid(row=4, column=0, columnspan=3, sticky=tk.W)
        ttk.Button(frame, text="Сгенерировать пароль", command=self.generate_password).grid(row=5, column=0, columnspan=3, pady=10)

        output_frame = ttk.LabelFrame(self.generator_tab, text="Сгенерированный пароль", padding=10)
        output_frame.pack(padx=10, pady=10, fill=tk.BOTH)
        self.password_var = tk.StringVar()
        password_entry_frame = ttk.Frame(output_frame)
        password_entry_frame.pack(fill=tk.X)
        self.password_entry = ttk.Entry(password_entry_frame, textvariable=self.password_var, width=30)
        self.password_entry.pack(side=tk.LEFT, expand=True, fill=tk.X)
        self.show_password_var = tk.BooleanVar(value=False)
        self.password_entry.config(show="*")
        ttk.Checkbutton(password_entry_frame, text="Показать", variable=self.show_password_var, command=self.toggle_password_visibility).pack(side=tk.RIGHT)

        ttk.Label(output_frame, text="Сложность пароля:").pack(anchor=tk.W)
        self.strength_var = tk.IntVar()
        self.strength_bar = ttk.Progressbar(output_frame, orient=tk.HORIZONTAL, length=200, mode='determinate', variable=self.strength_var)
        self.strength_bar.pack(fill=tk.X, pady=5)

        button_frame = ttk.Frame(output_frame)
        button_frame.pack(fill=tk.X, pady=5)
        ttk.Button(button_frame, text="Копировать", command=self.copy_password).pack(side=tk.LEFT, padx=5)
        ttk.Button(button_frame, text="Очистить", command=lambda: self.password_var.set("")).pack(side=tk.LEFT, padx=5)
        ttk.Button(button_frame, text="Сохранить", command=self.save_password_dialog).pack(side=tk.LEFT, padx=5)

    def setup_manager_tab(self):
        control_frame = ttk.Frame(self.manager_tab, padding=10)
        control_frame.pack(fill=tk.X)
        ttk.Button(control_frame, text="Обновить список", command=self.refresh_password_list).pack(side=tk.LEFT, padx=5)
        ttk.Button(control_frame, text="Добавить новый пароль", command=self.add_new_password_dialog).pack(side=tk.LEFT, padx=5)
        ttk.Label(control_frame, text="Поиск:").pack(side=tk.LEFT, padx=(10, 0))
        self.search_var = tk.StringVar()
        self.search_entry = ttk.Entry(control_frame, textvariable=self.search_var, width=20)
        self.search_entry.pack(side=tk.LEFT, padx=5)
        self.search_var.trace("w", lambda *args: self.filter_passwords())

        list_frame = ttk.Frame(self.manager_tab, padding=10)
        list_frame.pack(fill=tk.BOTH, expand=True)
        columns = ("description", "password")
        self.password_tree = ttk.Treeview(list_frame, columns=columns, show="headings", selectmode="browse")
        self.password_tree.heading("description", text="Описание")
        self.password_tree.heading("password", text="Пароль")
        self.password_tree.column("description", width=250)
        self.password_tree.column("password", width=200)

        for col in columns:
            self.password_tree.heading(col, command=lambda _col=col: self.sort_column(self.password_tree, _col, False))

        vscrollbar = ttk.Scrollbar(list_frame, orient="vertical", command=self.password_tree.yview)
        hscrollbar = ttk.Scrollbar(list_frame, orient="horizontal", command=self.password_tree.xview)
        self.password_tree.configure(yscrollcommand=vscrollbar.set, xscrollcommand=hscrollbar.set)
        vscrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        self.password_tree.pack(side=tk.TOP, fill=tk.BOTH, expand=True)
        hscrollbar.pack(side=tk.BOTTOM, fill=tk.X)

        self.refresh_password_list()

        action_frame = ttk.Frame(self.manager_tab, padding=10)
        action_frame.pack(fill=tk.X)
        ttk.Button(action_frame, text="Копировать", command=self.copy_selected_password).pack(side=tk.LEFT, padx=5)
        ttk.Button(action_frame, text="Редактировать", command=self.edit_selected_password).pack(side=tk.LEFT, padx=5)
        ttk.Button(action_frame, text="Удалить", command=self.delete_selected_password).pack(side=tk.LEFT, padx=5)
        ttk.Button(action_frame, text="Просмотреть", command=self.view_selected_password).pack(side=tk.LEFT, padx=5)

        self.password_tree.bind("<Double-1>", lambda event: self.edit_selected_password())

    def setup_keyboard_shortcuts(self):
        self.master.bind("<Control-g>", lambda event: self.tab_control.select(0))
        self.master.bind("<Control-m>", lambda event: self.tab_control.select(1))
        self.master.bind("<Control-s>", lambda event: self.tab_control.select(2)) 
        self.master.bind("<Control-c>", lambda event: self.copy_password())

    def generate_password(self):
        self.password_generator.password_length = int(self.length_var.get())
        self.password_generator.use_uppercase = self.use_uppercase.get()
        self.password_generator.use_lowercase = self.use_lowercase.get()
        self.password_generator.use_digits = self.use_digits.get()
        self.password_generator.use_symbols = self.use_symbols.get()

        new_password = self.password_generator.generate_password()
        self.password_var.set(new_password)
        self.update_strength_bar(new_password)

    def update_length(self, event):
        self.length_var.set(int(self.length_slider.get()))

    def update_strength_bar(self, password):
        score = self.password_generator.evaluate_password_strength(password)
        self.strength_var.set(score)
        if score < 40:
            self.strength_bar.config(style="red.Horizontal.TProgressbar")
        elif score < 70:
            self.strength_bar.config(style="yellow.Horizontal.TProgressbar")
        else:
            self.strength_bar.config(style="green.Horizontal.TProgressbar")

    def toggle_password_visibility(self):
        if self.show_password_var.get():
            self.password_entry.config(show="")
        else:
            self.password_entry.config(show="*")

    def copy_password(self):
        password = self.password_var.get()
        if password:
            pyperclip.copy(password)
            messagebox.showinfo("Успешно", "Пароль скопирован в буфер обмена!")
        else:
            messagebox.showerror("Ошибка", "Нет пароля для копирования.")

    def save_password_dialog(self):
        password = self.password_var.get()
        if not password:
            messagebox.showerror("Ошибка", "Сначала сгенерируйте пароль!")
            return

        description = simpledialog.askstring("Сохранить пароль", "Введите описание для пароля:")
        if description:
            self.password_manager.add_password(password, description)
            messagebox.showinfo("Успешно", "Пароль сохранен!")
            self.refresh_password_list()

    def add_new_password_dialog(self):
        """Prompt the user to add a new password manually."""
        def save_new_password():
            description = description_entry.get()
            password = password_entry.get()

            if description and password:
                self.password_manager.add_password(password, description)
                messagebox.showinfo("Успех", "Пароль добавлен!")
                add_dialog.destroy()
                self.refresh_password_list()
            else:
                messagebox.showerror("Ошибка", "Описание и пароль должны быть заполнены!")
                
        def paste_from_clipboard():
            try:
                clipboard_content = pyperclip.paste()
                password_entry.delete(0, tk.END)
                password_entry.insert(0, clipboard_content)
            except Exception as e:
                messagebox.showerror("Ошибка", f"Не удалось вставить из буфера обмена: {str(e)}")

        add_dialog = tk.Toplevel(self.master)
        add_dialog.title("Добавить новый пароль")

        ttk.Label(add_dialog, text="Описание:").grid(row=0, column=0, padx=5, pady=5)
        description_entry = ttk.Entry(add_dialog, width=30)
        description_entry.grid(row=0, column=1, padx=5, pady=5)

        ttk.Label(add_dialog, text="Пароль:").grid(row=1, column=0, padx=5, pady=5)
        
        # Создаем фрейм для поля ввода пароля и кнопки вставки
        password_frame = ttk.Frame(add_dialog)
        password_frame.grid(row=1, column=1, padx=5, pady=5, sticky=tk.W+tk.E)
        
        password_entry = ttk.Entry(password_frame, width=25, show="*")
        password_entry.pack(side=tk.LEFT, fill=tk.X, expand=True)
        
        paste_button = ttk.Button(password_frame, text="Вставить", command=paste_from_clipboard)
        paste_button.pack(side=tk.RIGHT, padx=(5, 0))

        show_password_var = tk.BooleanVar(value=False)
        def toggle_password_visibility():
            if show_password_var.get():
                password_entry.config(show="")
            else:
                password_entry.config(show="*")

        ttk.Checkbutton(add_dialog, text="Показать пароль", variable=show_password_var,
                        command=toggle_password_visibility).grid(row=2, column=1, padx=5, pady=5, sticky=tk.E)

        ttk.Button(add_dialog, text="Сохранить", command=save_new_password).grid(row=3, column=0, columnspan=2, padx=5, pady=5)

    def refresh_password_list(self):
        for item in self.password_tree.get_children():
            self.password_tree.delete(item)

        passwords = self.password_manager.get_all_passwords()
        for i, password_data in enumerate(passwords):
            self.password_tree.insert("", tk.END, str(i), values=(password_data["description"], password_data["password"]))

        self.filter_passwords()

    def filter_passwords(self):
        search_term = self.search_var.get().lower()
        for item in self.password_tree.get_children():
            description = self.password_tree.item(item, "values")[0].lower()
            password = self.password_tree.item(item, "values")[1].lower()
            if search_term in description or search_term in password:
                self.password_tree.item(item, tags=())
            else:
                self.password_tree.item(item, tags=("hidden",))
        self.password_tree.tag_configure("hidden", foreground="#ddd")

    def sort_column(self, tree, col, reverse):
        l = [(tree.set(k, col), k) for k in tree.get_children('')]
        l.sort(reverse=reverse)
        for index, (val, k) in enumerate(l):
            tree.move(k, '', index)
        tree.heading(col, command=lambda: self.sort_column(tree, col, not reverse))

    def copy_selected_password(self):
        selected_item = self.password_tree.selection()
        if not selected_item:
            messagebox.showerror("Ошибка", "Выберите пароль для копирования.")
            return

        item_id = selected_item[0]
        index = int(item_id)
        password_data = self.password_manager.get_password(index)

        if password_data:
            pyperclip.copy(password_data["password"])
            messagebox.showinfo("Успешно", "Пароль скопирован в буфер обмена!")
        else:
            messagebox.showerror("Ошибка", "Не удалось получить пароль.")

    def view_selected_password(self):
        selected_item = self.password_tree.selection()
        if not selected_item:
            messagebox.showerror("Ошибка", "Выберите пароль для просмотра.")
            return

        item_id = selected_item[0]
        index = int(item_id)
        password_data = self.password_manager.get_password(index)

        if password_data:
            view_dialog = tk.Toplevel(self.master)
            view_dialog.title("Просмотр пароля")

            ttk.Label(view_dialog, text="Описание:").grid(row=0, column=0, padx=5, pady=5, sticky=tk.W)
            ttk.Label(view_dialog, text=password_data["description"]).grid(row=0, column=1, padx=5, pady=5, sticky=tk.W)
            ttk.Label(view_dialog, text="Пароль:").grid(row=1, column=0, padx=5, pady=5, sticky=tk.W)
            password_entry = ttk.Entry(view_dialog, width=50)
            password_entry.grid(row=1, column=1, padx=5, pady=5, sticky=tk.W)
            password_entry.insert(0, password_data["password"])
            password_entry.config(state='readonly')
        else:
            messagebox.showerror("Ошибка", "Не удалось получить данные пароля.")

    def edit_selected_password(self):
        selected_item = self.password_tree.selection()
        if not selected_item:
            messagebox.showerror("Ошибка", "Выберите пароль для редактирования.")
            return

        item_id = selected_item[0]
        index = int(item_id)
        password_data = self.password_manager.get_password(index)

        if not password_data:
            messagebox.showerror("Ошибка", "Не удалось получить данные пароля.")
            return

        def save_edited_password():
            description = description_entry.get()
            password = password_entry.get()

            if description and password:
                self.password_manager.update_password(index, password, description)
                messagebox.showinfo("Успех", "Пароль обновлен!")
                edit_dialog.destroy()
                self.refresh_password_list()
            else:
                messagebox.showerror("Ошибка", "Описание и пароль должны быть заполнены!")

        def paste_from_clipboard():
            try:
                clipboard_content = pyperclip.paste()
                password_entry.delete(0, tk.END)
                password_entry.insert(0, clipboard_content)
            except Exception as e:
                messagebox.showerror("Ошибка", f"Не удалось вставить из буфера обмена: {str(e)}")

        edit_dialog = tk.Toplevel(self.master)
        edit_dialog.title("Редактировать пароль")

        ttk.Label(edit_dialog, text="Описание:").grid(row=0, column=0, padx=5, pady=5)
        description_entry = ttk.Entry(edit_dialog, width=30)
        description_entry.insert(0, password_data["description"])
        description_entry.grid(row=0, column=1, padx=5, pady=5)

        ttk.Label(edit_dialog, text="Пароль:").grid(row=1, column=0, padx=5, pady=5)
        
        # Создаем фрейм для поля ввода пароля и кнопки вставки
        password_frame = ttk.Frame(edit_dialog)
        password_frame.grid(row=1, column=1, padx=5, pady=5, sticky=tk.W+tk.E)
        
        password_entry = ttk.Entry(password_frame, width=25, show="*")
        password_entry.insert(0, password_data["password"])
        password_entry.pack(side=tk.LEFT, fill=tk.X, expand=True)
        
        paste_button = ttk.Button(password_frame, text="Вставить", command=paste_from_clipboard)
        paste_button.pack(side=tk.RIGHT, padx=(5, 0))

        show_password_var = tk.BooleanVar(value=False)
        def toggle_password_visibility():
            if show_password_var.get():
                password_entry.config(show="")
            else:
                password_entry.config(show="*")

        ttk.Checkbutton(edit_dialog, text="Показать пароль", variable=show_password_var, 
                        command=toggle_password_visibility).grid(row=2, column=1, padx=5, pady=5, sticky=tk.E)
        ttk.Button(edit_dialog, text="Сохранить", command=save_edited_password).grid(row=3, column=0, columnspan=2, padx=5, pady=5)

    def delete_selected_password(self):
        selected_item = self.password_tree.selection()
        if not selected_item:
            messagebox.showerror("Ошибка", "Выберите пароль для удаления.")
            return

        item_id = selected_item[0]
        index = int(item_id)

        if messagebox.askyesno("Подтверждение", "Вы уверены, что хотите удалить этот пароль?"):
            if self.password_manager.delete_password(index):
                messagebox.showinfo("Успех", "Пароль удален.")
                self.refresh_password_list()
            else:
                messagebox.showerror("Ошибка", "Не удалось удалить пароль.")