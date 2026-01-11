import sys
import csv
import json
import random
import uuid
from datetime import date, timedelta

from PyQt6.QtCore import Qt, QSize, QProcess
from PyQt6.QtGui import (
    QIcon, QStandardItem, QStandardItemModel, QAction, QKeySequence, QShortcut
)
from PyQt6.QtWidgets import (
    QApplication, QWidget, QVBoxLayout, QHBoxLayout, QLabel, QSpinBox,
    QComboBox, QPushButton, QFileDialog, QTableView, QGroupBox, QFormLayout,
    QCheckBox, QLineEdit, QTabWidget, QMessageBox, QMenuBar
)

from faker import Faker

PATRONYMICS_M = ["Алексеевич", "Иванович", "Петрович", "Сергеевич", "Андреевич", "Максимович", "Николаевич"]
PATRONYMICS_F = ["Алексеевна", "Ивановна", "Петровна", "Сергеевна", "Андреевна", "Максимовна", "Николаевна"]

EDUCATION = [
    "Среднее общее", "Среднее профессиональное", "Незаконченное высшее",
    "Бакалавр", "Специалитет/Магистр", "Аспирантура/Кандидат наук"
]
MARITAL = ["не женат/не замужем", "женат/замужем", "в разводе", "вдовец/вдова"]

HOBBIES = ["чтение", "фотография", "рисование", "бег", "йога", "игры", "садоводство",
           "кулинария", "плавание", "велоспорт", "путешествия", "вязание",
           "гитара", "пианино", "шахматы"]
CUISINES = ["итальянская", "японская", "грузинская", "русская", "индийская", "мексиканская", "тайская", "французская"]
MUSIC = ["рок", "поп", "джаз", "классика", "инди", "рэп", "электроника", "метал"]
MOVIES = ["драма", "комедия", "триллер", "фантастика", "боевик", "документальный", "ужасы", "приключения"]
COLORS = ["красный", "оранжевый", "жёлтый", "зелёный", "голубой", "синий", "фиолетовый",
          "чёрный", "белый", "серый", "розовый", "бирюзовый", "бордовый", "бежевый"]

OS_LIST = ["Windows 11", "Windows 10", "macOS 14", "Ubuntu 24.04", "Android 14", "iOS 17"]
BROWSERS = ["Chrome", "Firefox", "Edge", "Safari", "Opera"]
CAR_MODELS = ["Toyota Camry", "Hyundai Solaris", "Kia Rio", "Skoda Octavia", "Volkswagen Polo", "Lada Vesta", "BMW 3"]
PET_TYPES = ["кот", "собака", "рыбки", "попугай", "хомяк", "морская свинка"]
VK_DOMAINS = ["id", "club", "public"]
IG_SUFFIX = ["", ".", "_", "__", ".official", ".blog"]
TG_SUFFIX = ["", "_bot", "_ch", "_ru"]

def random_date(start_year=1950, end_year=2007):
    start = date(start_year, 1, 1)
    end = date(end_year, 12, 31)
    delta = (end - start).days
    return start + timedelta(days=random.randint(0, delta))

def mask_card(num: str) -> str:
    digits = ''.join(ch for ch in num if ch.isdigit())
    if len(digits) < 4:
        return "**** **** **** ****"
    return "**** **** **** " + digits[-4:]

def extract_lastname(fullname: str) -> str:
    parts = fullname.split()
    return parts[-1] if parts else ""

def child_lastname_from_father(father_last: str, child_gender: str, locale: str) -> str:
    if not father_last:
        return father_last
    if not locale.startswith("ru"):
        return father_last
    last = father_last
    if child_gender == "женский":
        if last.endswith(("ов","ев","ёв","ин","ын")):
            return last + "а"
        if last.endswith(("ский","цкий")):
            return last[:-2] + "ая"
        if last.endswith(("ый","ий")):
            return last[:-2] + "ая"
        if last.endswith(("ко","енко","ук","чук","о")):
            return last
        if last.endswith(("а","я")):
            return last
        return last + "а"
    return last

def generate_children(fake: Faker, locale: str, min_children: int, max_children: int):
    cnt = random.randint(min_children, max_children)
    if cnt == 0:
        return [], "", ""
    kids = []
    for _ in range(cnt):
        gender = random.choice(["мужской", "женский"])
        if locale.startswith("ru"):
            first = fake.first_name_male() if gender == "мужской" else fake.first_name_female()
            last = gendered_last_name(fake, locale, gender)
        else:
            first = fake.first_name_male() if gender == "мужской" else fake.first_name_female()
            last = gendered_last_name(fake, locale, gender)
        bd = random_date(2005, date.today().year - 1)
        kids.append({"имя": f"{first} {last}", "пол": gender, "дата рождения": format_date_ru(bd)})
    names = "; ".join(k["имя"] for k in kids)
    bds = "; ".join(k["дата рождения"] for k in kids)
    return kids, names, bds

def random_income():
    return random.randrange(40_000, 350_000, 1000)

def chance(p=0.5):
    return random.random() < p

def patronymic(gender: str):
    return random.choice(PATRONYMICS_M if gender == "мужской" else PATRONYMICS_F)

def socials(username_base: str):
    vk = f"https://vk.com/{random.choice(VK_DOMAINS)}{random.randint(10000,999999)}"
    ig = f"https://instagram.com/{username_base}{random.choice(IG_SUFFIX)}"
    tg = f"@{username_base}{random.choice(TG_SUFFIX)}"
    return vk, ig, tg

def join_nonempty(*parts):
    return " ".join([p for p in parts if p])

def gendered_last_name(fake: Faker, locale: str, gender: str) -> str:
    if locale.startswith("ru"):
        if gender == "мужской" and hasattr(fake, "last_name_male"):
            return fake.last_name_male()
        if gender == "женский" and hasattr(fake, "last_name_female"):
            return fake.last_name_female()
    return fake.last_name()

def format_date_ru(d: date) -> str:
    return d.strftime("%d.%m.%Y")

def ru_phone_normalize(phone: str) -> str:
    digits = ''.join(ch for ch in phone if ch.isdigit())
    if digits.startswith('8') and len(digits) == 11:
        digits = '7' + digits[1:]
    if digits.startswith('7') and len(digits) == 11:
        return '+7' + digits[1:]
    if digits.startswith('9') and len(digits) == 10:
        return '+7' + digits
    return phone

def make_username(first: str, last: str) -> str:
    table = {
        "а":"a","б":"b","в":"v","г":"g","д":"d","е":"e","ё":"e","ж":"zh","з":"z","и":"i","й":"y",
        "к":"k","л":"l","м":"m","н":"n","о":"o","п":"p","р":"r","с":"s","т":"t","у":"u","ф":"f",
        "х":"h","ц":"c","ч":"ch","ш":"sh","щ":"sch","ь":"","ы":"y","ъ":"","э":"e","ю":"yu","я":"ya",
        " ":"_"
    }
    base = (first + "." + last).lower()
    translit = "".join(table.get(ch, ch) for ch in base)
    cleaned = "".join(ch for ch in translit if ch.isalnum() or ch in "._-")
    return cleaned.strip("._-") or "user"

def realistic_email(first: str, last: str) -> str:
    domains = ["yandex.ru", "mail.ru", "gmail.com", "rambler.ru", "yahoo.com"]
    weights = [0.35, 0.25, 0.25, 0.1, 0.05]
    user = make_username(first, last)
    suffix = str(random.randint(1, 999)) if random.random() < 0.35 else ""
    return f"{user}{suffix}@{random.choices(domains, weights=weights, k=1)[0]}"

def marital_by_age(age: int) -> str:
    r = random.random()
    if age < 22:
        return "не женат/не замужем"
    if age < 30:
        return "женат/замужем" if r < 0.45 else "не женат/не замужем"
    if age < 45:
        return "женат/замужем" if r < 0.7 else ("в разводе" if r < 0.85 else "не женат/не замужем")
    if age < 65:
        return "женат/замужем" if r < 0.75 else ("в разводе" if r < 0.9 else "вдовец/вдова")
    return "вдовец/вдова" if r < 0.25 else "женат/замужем"

def spouse_profile(fake: Faker, locale: str, gender: str, person_last: str, person_age: int):
    sp_gender = "женский" if gender == "мужской" else "мужской"
    first = fake.first_name_female() if sp_gender == "женский" else fake.first_name_male()
    if locale.startswith("ru") and random.random() < 0.65:
        last = person_last if sp_gender == "женский" else gendered_last_name(fake, locale, sp_gender)
    else:
        last = gendered_last_name(fake, locale, sp_gender)
    age_diff = random.randint(-6, 6)
    sp_age = max(18, person_age + age_diff)
    return f"{first} {last}", sp_age

def children_plan_by_age(parent_age: int, min_children: int, max_children: int) -> int:
    if parent_age < 22:
        return 0
    if parent_age < 28:
        hi = min(max_children, 1)
        return random.randint(min_children, hi)
    if parent_age < 36:
        hi = min(max_children, 2)
        return random.randint(min_children, hi)
    if parent_age < 46:
        hi = min(max_children, 3)
        return random.randint(min_children, hi)
    return 0

def generate_children_from_parent(fake: Faker, locale: str, parent_gender: str, parent_dob: date, count: int, father_last: str = ""):
    kids = []
    if count <= 0:
        return kids, "", ""
    earliest = date(parent_dob.year + 18, parent_dob.month, parent_dob.day)
    current = earliest + timedelta(days=random.randint(0, 5*365))
    for i in range(count):
        gender = random.choice(["мужской", "женский"])
        first = fake.first_name_male() if gender == "мужской" else fake.first_name_female()
        last = child_lastname_from_father(father_last, gender, locale)
        bd = min(current, date.today() - timedelta(days=365))
        kids.append({"имя": f"{first} {last}", "пол": gender, "дата рождения": format_date_ru(bd)})
        gap_years = random.randint(1, 5)
        current = bd.replace(year=min(bd.year + gap_years, date.today().year - 1))
    names = "; ".join(k["имя"] for k in kids)
    bds = "; ".join(k["дата рождения"] for k in kids)
    return kids, names, bds

def income_by_profile(age: int, education: str) -> int:
    base = 40_000 if age < 23 else 70_000 if age < 30 else 110_000 if age < 40 else 120_000 if age < 55 else 90_000
    mult = 1.0
    if education in ("Бакалавр", "Специалитет/Магистр"):
        mult = 1.2
    elif education == "Аспирантура/Кандидат наук":
        mult = 1.35
    elif education == "Среднее профессиональное":
        mult = 0.9
    noise = random.randint(-15_000, 25_000)
    return max(30_000, int(base * mult) + noise)

def os_by_age(age: int) -> str:
    if age < 25:
        return random.choices(["Android 14", "iOS 17", "Windows 11", "macOS 14"], [0.45,0.35,0.12,0.08], k=1)[0]
    if age < 40:
        return random.choices(["Windows 11", "Android 14", "iOS 17", "macOS 14"], [0.4,0.3,0.2,0.1], k=1)[0]
    if age < 60:
        return random.choices(["Windows 10", "Windows 11", "Android 14", "iOS 17"], [0.45,0.25,0.2,0.1], k=1)[0]
    return random.choices(["Windows 10", "Android 14", "iOS 17"], [0.6,0.25,0.15], k=1)[0]

def browser_by_age(age: int) -> str:
    if age < 25:
        return random.choices(["Chrome","Safari","Firefox","Edge","Opera"], [0.55,0.2,0.1,0.1,0.05], k=1)[0]
    if age < 40:
        return random.choices(["Chrome","Firefox","Edge","Safari","Opera"], [0.6,0.15,0.15,0.07,0.03], k=1)[0]
    if age < 60:
        return random.choices(["Chrome","Edge","Firefox","Opera","Safari"], [0.55,0.25,0.15,0.03,0.02], k=1)[0]
    return random.choices(["Chrome","Edge","Firefox"], [0.5,0.4,0.1], k=1)[0]

def marital_by_age_gender(age: int, gender: str) -> str:
    r = random.random()
    if age < 22:
        code = "single"
    elif age < 30:
        code = "married" if r < 0.45 else "single"
    elif age < 45:
        if r < 0.7:
            code = "married"
        elif r < 0.85:
            code = "divorced"
        else:
            code = "single"
    elif age < 65:
        if r < 0.75:
            code = "married"
        elif r < 0.9:
            code = "divorced"
        else:
            code = "widowed"
    else:
        code = "widowed" if r < 0.25 else "married"

    if gender == "мужской":
        return {"single": "не женат", "married": "женат", "divorced": "в разводе", "widowed": "вдовец"}[code]
    else:
        return {"single": "не замужем", "married": "замужем", "divorced": "в разводе", "widowed": "вдова"}[code]

def car_by_age(age: int) -> bool:
    if age < 23:
        return random.random() < 0.15
    if age < 35:
        return random.random() < 0.35
    if age < 55:
        return random.random() < 0.5
    return random.random() < 0.4

class ProfileGenerator:
    def __init__(self, locale="ru_RU", seed=None, min_age=18, max_age=75,
                 with_children=True, min_children=0, max_children=3):
        self.fake = Faker(locale)
        if seed is not None:
            random.seed(seed)
            Faker.seed(seed)
        self.locale = locale
        self.min_age = min_age
        self.max_age = max_age
        self.with_children = with_children
        self.min_children = min_children
        self.max_children = max_children

    def _dob_by_age(self, age: int) -> date:
        today = date.today()
        start = date(today.year - age, 1, 1)
        end = date(today.year - age, 12, 31)
        delta = (end - start).days
        return start + timedelta(days=random.randint(0, delta))

    def _address(self):
        addr = self.fake.address().replace("\n", ", ")
        postal = "".join(ch for ch in self.fake.postcode() if ch.isdigit() or ch == "-")
        city = getattr(self.fake, "city", lambda: "")()
        street = getattr(self.fake, "street_name", lambda: "")()
        house = str(random.randint(1, 200))
        apartment = str(random.randint(1, 300))
        country = getattr(self.fake, "current_country", lambda: "")() or self.fake.country()
        region = getattr(self.fake, "state", lambda: "")()
        return {
            "страна": country,
            "регион": region,
            "город": city,
            "улица": street,
            "дом": house,
            "квартира": apartment,
            "индекс": postal,
            "полный_адрес": addr
        }

    def _one(self):
        gender = random.choice(["мужской", "женский"])
        if self.locale.startswith("ru"):
            first = self.fake.first_name_male() if gender == "мужской" else self.fake.first_name_female()
            last = gendered_last_name(self.fake, self.locale, gender)
            middle = patronymic(gender)
        else:
            first = self.fake.first_name_male() if gender == "мужской" else self.fake.first_name_female()
            last = gendered_last_name(self.fake, self.locale, gender)
            middle = ""
        age = random.randint(self.min_age, self.max_age)
        dob = self._dob_by_age(age)
        marital = marital_by_age_gender(age, gender)
        spouse = ""
        if marital in ("женат", "замужем"):
            spouse, _ = spouse_profile(self.fake, self.locale, gender, last, age)
        father_last = last if gender == "мужской" else (extract_lastname(spouse) if spouse else last)
        children_obj, children_names, children_bds = [], "", ""
        planned = 0
        if self.with_children:
            planned = children_plan_by_age(age, self.min_children, self.max_children)
            if marital in ("вдовец", "вдова"):
                planned = max(planned, 1)

        if planned > 0:
            children_obj, children_names, children_bds = generate_children_from_parent(
                self.fake, self.locale, gender, dob, planned, father_last
            )
        children_obj, children_names, children_bds = [], "", ""
        planned = 0
        if self.with_children:
            planned = children_plan_by_age(age, self.min_children, self.max_children)
        if marital in ("вдовец", "вдова"):
            planned = max(planned, 1)
        if planned > 0:
            children_obj, children_names, children_bds = generate_children_from_parent(
                self.fake, self.locale, gender, dob, planned, father_last
            )
        phone = self.fake.phone_number()
        if self.locale.startswith("ru"):
            phone = ru_phone_normalize(phone)
        email = realistic_email(first, last)
        company = self.fake.company()
        job = self.fake.job()
        education = random.choice(EDUCATION)
        income_rub = income_by_profile(age, education)
        vk, ig, tg = socials(username_base=make_username(first, last))
        os_name = os_by_age(age)
        browser = browser_by_age(age)
        min_register_age = max(14, 2025 - dob.year)
        registered_at = self.fake.date_time_between(start_date=f"-{max(1, min_register_age)}y", end_date="-1y")
        last_active = self.fake.date_time_between(start_date=registered_at, end_date="now")
        ip = self.fake.ipv4_public()
        card = mask_card(self.fake.credit_card_number())
        fav_color = random.choice(COLORS)
        fav_cuisine = random.choice(CUISINES)
        fav_music = random.choice(MUSIC)
        fav_movie = random.choice(MOVIES)
        address = self._address()
        has_car = car_by_age(age)
        car_model = random.choice(CAR_MODELS) if has_car else ""
        has_pets = chance(0.3)
        pets = "; ".join(random.sample(PET_TYPES, k=random.randint(1, 2))) if has_pets else ""
        hobbies_list = "; ".join(random.sample(HOBBIES, k=random.randint(2, 5)))
        interests = "; ".join(random.sample(HOBBIES + MUSIC + MOVIES, k=random.randint(3, 7)))
        record = {
            "Id пользователя": str(uuid.uuid4()),
            "Имя": first,
            "Отчество": middle,
            "Фамилия": last,
            "Пол": gender,
            "Дата рождения": format_date_ru(dob),
            "Возраст": age,
            "Семейное положение": marital,
            "Имя супруга(и)": spouse,
            "Количество детей": len(children_obj),
            "Имена детей": children_names,
            "Дата(ы) рождения детей": children_bds,
            "Почта": email,
            "Телефон": phone,
            "Страна": address["страна"],
            "Регион": address["регион"],
            "Город": address["город"],
            "Улица": address["улица"],
            "Дом": address["дом"],
            "Квартира": address["квартира"],
            "Индекс": address["индекс"],
            "Полный адрес": address["полный_адрес"],
            "Компания": company,
            "Должность": job,
            "Месячный доход(руб)": income_rub,
            "Уровень образования": education,
            "Vk": vk,
            "Instagram": ig,
            "Telegram": tg,
            "Операционная система": os_name,
            "Браузер": browser,
            "Дата регистрации": registered_at.isoformat(sep=" "),
            "последняя активность": last_active.isoformat(sep=" "),
            "Ip адрес": ip,
            "Карта": card,
            "Любимый цвет": fav_color,
            "Любимая кухня": fav_cuisine,
            "Любимая музыка": fav_music,
            "Любимый жанр кино": fav_movie,
            "Владелец авто": "да" if has_car else "нет",
            "Модель авто": car_model,
            "Питомцы": pets,
            "Хобби": hobbies_list,
            "Интересы": interests,
        }
        record["_дети"] = children_obj
        return record

    def generate(self, n: int):
        return [self._one() for _ in range(n)]

class MainWindow(QWidget):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Генератор тестовых профилей")
        self.setMinimumSize(QSize(1100, 700))
        try:
            self.setWindowIcon(QIcon.fromTheme("user-group"))
        except:
            pass
        self.records = []
        self.tabs = QTabWidget(self)
        self.tab_options = QWidget()
        self.tab_preview = QWidget()
        self.tabs.addTab(self.tab_options, "Настройки")
        self.tabs.addTab(self.tab_preview, "Результат")
        self._build_options()
        self.model = QStandardItemModel(self)
        self._build_preview()
        root = QVBoxLayout(self)
        root.addWidget(self.tabs)
        self._install_apps_menu(root)
        self.setLayout(root)
        self._apply_styles()

    def _build_options(self):
        layout = QVBoxLayout(self.tab_options)
        box_main = QGroupBox("Основные параметры")
        form = QFormLayout(box_main)
        self.locale_cb = QComboBox()
        self.locale_cb.addItems(["ru_RU", "en_US", "de_DE", "fr_FR", "it_IT", "es_ES"])
        self.count_sb = QSpinBox()
        self.count_sb.setRange(1, 100000)
        self.count_sb.setValue(50)
        self.min_age_sb = QSpinBox(); self.min_age_sb.setRange(0, 120); self.min_age_sb.setValue(18)
        self.max_age_sb = QSpinBox(); self.max_age_sb.setRange(0, 120); self.max_age_sb.setValue(75)
        self.seed_le = QLineEdit(); self.seed_le.setPlaceholderText("опционально (число)")
        form.addRow("Локаль:", self.locale_cb)
        form.addRow("Количество записей:", self.count_sb)
        age_box = QWidget(); age_l = QHBoxLayout(age_box); age_l.setContentsMargins(0, 0, 0, 0)
        age_l.addWidget(QLabel("мин:")); age_l.addWidget(self.min_age_sb); age_l.addSpacing(10)
        age_l.addWidget(QLabel("макс:")); age_l.addWidget(self.max_age_sb)
        form.addRow("Возраст:", age_box)
        form.addRow("Seed генерации:", self.seed_le)
        box_children = QGroupBox("Дети")
        form_children = QFormLayout(box_children)
        self.with_children_cb = QCheckBox("Генерировать детей"); self.with_children_cb.setChecked(True)
        self.with_children_cb.toggled.connect(self.on_children_toggle)
        self.min_children_sb = QSpinBox(); self.min_children_sb.setRange(0, 8); self.min_children_sb.setValue(0)
        self.max_children_sb = QSpinBox(); self.max_children_sb.setRange(0, 8); self.max_children_sb.setValue(3)
        row = QWidget(); rowl = QHBoxLayout(row); rowl.setContentsMargins(0, 0, 0, 0)
        rowl.addWidget(QLabel("мин:")); rowl.addWidget(self.min_children_sb); rowl.addSpacing(10)
        rowl.addWidget(QLabel("макс:")); rowl.addWidget(self.max_children_sb)
        form_children.addRow(self.with_children_cb)
        form_children.addRow("Количество детей:", row)
        btns = QWidget(); hb = QHBoxLayout(btns); hb.setContentsMargins(0, 0, 0, 0)
        self.generate_btn = QPushButton("Сгенерировать"); self.generate_btn.clicked.connect(self.on_generate)
        self.clear_btn = QPushButton("Очистить результат"); self.clear_btn.clicked.connect(self.on_clear)
        hb.addStretch(1); hb.addWidget(self.generate_btn); hb.addWidget(self.clear_btn)
        layout.addWidget(box_main)
        layout.addWidget(box_children)
        layout.addStretch(1)
        layout.addWidget(btns)
        self.on_children_toggle(self.with_children_cb.isChecked())

    def on_children_toggle(self, checked: bool):
        self.min_children_sb.setEnabled(checked)
        self.max_children_sb.setEnabled(checked)

    def _install_apps_menu(self, root_layout: QVBoxLayout):
        mb = QMenuBar(self)
        apps_menu = mb.addMenu("Приложения")
        act = QAction("Выбрать приложение...  (Ctrl+Alt+L)", self)
        act.triggered.connect(self.show_app_launcher)
        apps_menu.addAction(act)
        root_layout.setMenuBar(mb)

        sc = QShortcut(QKeySequence("Ctrl+Alt+L"), self)
        sc.setContext(Qt.ShortcutContext.ApplicationShortcut)
        sc.activated.connect(self.show_app_launcher)

    def show_app_launcher(self):
        import os, sys
        candidates = [
            "Launcher.exe", "launcher.exe", "NotesPM.exe",
            "launcher.py", "launcher.pyw"
        ]
        search_dirs = [
            os.path.dirname(sys.argv[0]),
            os.getcwd(),
            os.path.dirname(__file__),
        ]
        for d in dict.fromkeys(search_dirs):
            for name in candidates:
                path = os.path.join(d, name)
                if os.path.isfile(path):
                    if path.lower().endswith((".py", ".pyw")):
                        QProcess.startDetached(sys.executable, [path])
                    else:
                        QProcess.startDetached(path, [])
                    return
        QMessageBox.warning(self, "Приложения", "Файл Launcher не найден.")

    def _build_preview(self):
        layout = QVBoxLayout(self.tab_preview)
        self.table = QTableView(self); self.table.setModel(self.model)
        self.table.setAlternatingRowColors(True)
        self.table.setSortingEnabled(True)
        self.table.setSelectionBehavior(QTableView.SelectionBehavior.SelectItems)
        self.table.setSelectionMode(QTableView.SelectionMode.ExtendedSelection)
        self.table.setWordWrap(False)
        self.copy_act = QAction("Копировать", self)
        self.copy_act.setShortcut(QKeySequence.StandardKey.Copy)
        self.copy_act.triggered.connect(self.copy_selection)
        self.addAction(self.copy_act)
        self.table.setContextMenuPolicy(Qt.ContextMenuPolicy.ActionsContextMenu)
        self.table.addAction(self.copy_act)
        export_box = QGroupBox("Экспорт")
        hb = QHBoxLayout(export_box)
        self.export_csv_btn = QPushButton("Экспорт CSV"); self.export_csv_btn.clicked.connect(self.export_csv)
        self.export_json_btn = QPushButton("Экспорт JSON"); self.export_json_btn.clicked.connect(self.export_json)
        hb.addStretch(1); hb.addWidget(self.export_csv_btn); hb.addWidget(self.export_json_btn)
        layout.addWidget(self.table, stretch=1)
        layout.addWidget(export_box)

    def _apply_styles(self):
        self.setStyleSheet("""
            QWidget { font-size: 14px; }
            QTabWidget::pane { border: 1px solid #2e3b4e; border-radius: 10px; }
            QTabBar::tab { background: #1f2633; color: #e8eef8; padding: 8px 14px; border-top-left-radius: 8px; border-top-right-radius: 8px; }
            QTabBar::tab:selected { background: #2c3648; }
            QGroupBox { border: 1px solid #3a4a63; border-radius: 10px; margin-top: 12px; }
            QGroupBox::title { subcontrol-origin: margin; left: 12px; padding: 0 6px; color: #a5b4cf; }
            QPushButton { background: #3a6df0; color: white; border-radius: 10px; padding: 8px 14px; }
            QPushButton:hover { background: #335fde; }
            QPushButton:disabled { background: #4b5b77; }
            QTableView { background: #0f1420; color: #d6deea; gridline-color: #2b3852; }
            QHeaderView::section { background: #162235; color: #b6c3da; padding: 6px; border: 0; }
            QLineEdit, QComboBox, QSpinBox { background: #131a29; color: #e8eef8; border: 1px solid #2b3852; border-radius: 8px; padding: 4px 6px; }
            QLabel, QCheckBox { color: #d6deea; }
        """)

    def on_clear(self):
        self.records = []
        self.model.clear()

    def on_generate(self):
        try:
            locale = self.locale_cb.currentText()
            count = self.count_sb.value()
            min_age = self.min_age_sb.value()
            max_age = self.max_age_sb.value()
            if min_age > max_age:
                raise ValueError("Минимальный возраст больше максимального.")
            seed_text = self.seed_le.text().strip()
            seed = int(seed_text) if seed_text else None
            with_children = self.with_children_cb.isChecked()
            min_children = self.min_children_sb.value()
            max_children = self.max_children_sb.value()
            if min_children > max_children:
                raise ValueError("Мин. количество детей больше макс.")
            gen = ProfileGenerator(
                locale=locale,
                seed=seed,
                min_age=min_age,
                max_age=max_age,
                with_children=with_children,
                min_children=min_children,
                max_children=max_children
            )
            self.records = gen.generate(count)
            self._fill_table(self.records)
            self.tabs.setCurrentIndex(1)
        except Exception as e:
            QMessageBox.critical(self, "Ошибка генерации", str(e))

    def _fill_table(self, data):
        columns = []
        for r in data:
            for k in r.keys():
                if k == "_дети":
                    continue
                if k not in columns:
                    columns.append(k)
        self.model.clear()
        self.model.setHorizontalHeaderLabels(columns)
        for row in data:
            items = []
            for col in columns:
                val = row.get(col, "")
                if isinstance(val, bool):
                    val = "да" if val else "нет"
                items.append(QStandardItem(str(val)))
            for it in items:
                it.setEditable(False)
            self.model.appendRow(items)
        self.table.resizeColumnsToContents()

    def export_csv(self):
        if not self.records:
            QMessageBox.information(self, "Нет данных", "Сначала сгенерируй данные.")
            return
        path, _ = QFileDialog.getSaveFileName(self, "Сохранить CSV", "профили.csv", "CSV Files (*.csv)")
        if not path:
            return
        flat = []
        for r in self.records:
            d = {k: v for k, v in r.items() if k != "_дети"}
            flat.append(d)
        cols = sorted({k for row in flat for k in row.keys()})
        with open(path, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=cols, delimiter=";")
            writer.writeheader()
            for row in flat:
                writer.writerow(row)
        QMessageBox.information(self, "Готово", f"Сохранено: {path}")

    def export_json(self):
        if not self.records:
            QMessageBox.information(self, "Нет данных", "Сначала сгенерируй данные.")
            return
        path, _ = QFileDialog.getSaveFileName(self, "Сохранить JSON", "профили.json", "JSON Files (*.json)")
        if not path:
            return
        with open(path, "w", encoding="utf-8") as f:
            json.dump(self.records, f, ensure_ascii=False, indent=2)
        QMessageBox.information(self, "Готово", f"Сохранено: {path}")

    def copy_selection(self):
        selection = self.table.selectionModel()
        if not selection or not selection.selectedIndexes():
            return
        indexes = selection.selectedIndexes()
        rows = sorted(set(i.row() for i in indexes))
        cols = sorted(set(i.column() for i in indexes))
        lines = []
        for r in rows:
            row_vals = []
            for c in cols:
                idx = self.model.index(r, c)
                val = self.model.data(idx)
                row_vals.append("" if val is None else str(val))
            lines.append("\t".join(row_vals))
        text = "\n".join(lines)
        QApplication.clipboard().setText(text)

def main():
    app = QApplication(sys.argv)
    w = MainWindow()
    w.show()
    sys.exit(app.exec())

if __name__ == "__main__":
    main()