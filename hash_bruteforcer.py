#!/usr/bin/env python3
import sys
import hashlib
import itertools
import string
import time
import os
import argparse
import traceback
import importlib.util
import tempfile
from concurrent.futures import ThreadPoolExecutor
from PyQt5.QtWidgets import (QApplication, QMainWindow, QLabel, QComboBox, 
                            QLineEdit, QPushButton, QTextEdit, QProgressBar, 
                            QSpinBox, QCheckBox, QGridLayout, QWidget, QGroupBox,
                            QTabWidget, QFileDialog, QHBoxLayout, QVBoxLayout,
                            QMessageBox)
from PyQt5.QtCore import QThread, pyqtSignal, Qt

# Глобальная переменная для хранения пользовательской функции хеширования
custom_hash_function = None

# Получаем все доступные алгоритмы хеширования
def get_available_hash_algorithms():
    # Стандартные алгоритмы
    standard_algorithms = [
        "MD5", "SHA1", "SHA224", "SHA256", "SHA384", "SHA512",
        "SHA3_224", "SHA3_256", "SHA3_384", "SHA3_512",
        "BLAKE2b", "BLAKE2s"
    ]
    
    # Проверяем, какие из алгоритмов доступны в текущей системе
    available = []
    for algo in standard_algorithms:
        try:
            # Пытаемся создать объект хеширования с этим алгоритмом
            if algo.startswith("BLAKE2"):
                # BLAKE2 требует указания длины дайджеста
                getattr(hashlib, algo.lower())(digest_size=32)
            else:
                getattr(hashlib, algo.lower())()
            available.append(algo)
        except (AttributeError, ValueError):
            # Этот алгоритм недоступен
            pass
    
    # Также получаем доступные алгоритмы через hashlib.algorithms_available
    # но убираем алгоритмы без дайджеста (shake)
    for algo in hashlib.algorithms_available:
        upper_algo = algo.upper()
        if upper_algo not in [a.upper() for a in available] and not "SHAKE" in upper_algo:
            # Проверяем, можем ли мы создать и использовать этот алгоритм
            try:
                h = hashlib.new(algo)
                h.update(b"test")
                h.hexdigest()
                available.append(algo.upper())
            except (TypeError, ValueError):
                # Некоторые алгоритмы могут быть недоступны или не поддерживать hexdigest
                pass
    
    # Добавляем пользовательский хеш если он доступен
    if custom_hash_function is not None:
        available.append("CUSTOM")
    
    # Сортируем для лучшего представления
    return sorted(available)

# Функция для получения хеша из текста с указанным алгоритмом
def get_hash(text, hash_type):
    try:
        algo = hash_type.lower()
        
        # Проверяем, если это пользовательский хеш
        if algo == "custom" and custom_hash_function is not None:
            try:
                result = custom_hash_function(text)
                # Убедимся, что результат представляет собой строку
                if not isinstance(result, str):
                    result = str(result)
                return result
            except Exception as e:
                print(f"Ошибка в пользовательской хеш-функции: {str(e)}")
                return hashlib.md5(text.encode()).hexdigest()
        
        # Обработка особых случаев
        if algo.startswith("blake2"):
            # BLAKE2 требует указания размера дайджеста
            h = getattr(hashlib, algo)(digest_size=32)
            h.update(text.encode())
            return h.hexdigest()
        elif "shake" in algo:
            # SHAKE требует указания длины вывода
            h = getattr(hashlib, algo)()
            h.update(text.encode())
            return h.hexdigest(128)  # Используем длину 128 байт
        elif algo in hashlib.algorithms_available:
            # Стандартные алгоритмы
            if hasattr(hashlib, algo):
                h = getattr(hashlib, algo)()
            else:
                h = hashlib.new(algo)
            h.update(text.encode())
            return h.hexdigest()
        else:
            # Если алгоритм не распознан, используем MD5
            return hashlib.md5(text.encode()).hexdigest()
    except Exception:
        # В случае ошибки используем MD5
        return hashlib.md5(text.encode()).hexdigest()

# Функция для проверки и загрузки пользовательской хеш-функции
def load_custom_hash_function(code):
    global custom_hash_function
    
    # Создаем временный файл для загрузки кода
    with tempfile.NamedTemporaryFile(suffix='.py', delete=False, mode='w') as temp_file:
        # Задаем шаблон функции, который ожидает строку и возвращает хеш
        # Добавляем необходимые импорты
        temp_file.write(f"""
import hashlib
import string
import base64
import binascii
import math
import zlib

def custom_hash(text):
{code}
""")
        temp_path = temp_file.name
    
    try:
        # Загружаем модуль с пользовательской функцией
        spec = importlib.util.spec_from_file_location("custom_hash_module", temp_path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        
        # Проверяем работоспособность функции
        test_result = module.custom_hash("test")
        
        # Сохраняем функцию глобально для использования
        custom_hash_function = module.custom_hash
        
        # Удаляем временный файл
        os.unlink(temp_path)
        
        return True, f"Функция успешно загружена. Тестовый хеш для 'test': {test_result}"
    except Exception as e:
        error_msg = f"Ошибка в коде хеш-функции: {str(e)}\n{traceback.format_exc()}"
        # Удаляем временный файл
        os.unlink(temp_path)
        return False, error_msg

class BruteForceWorker(QThread):
    update_progress = pyqtSignal(int, str)
    found_match = pyqtSignal(str, str)
    finished_task = pyqtSignal()
    
    def __init__(self, hash_type, target_hash, char_set, min_length, max_length):
        super().__init__()
        self.hash_type = hash_type
        self.target_hash = target_hash.lower()
        self.char_set = char_set
        self.min_length = min_length
        self.max_length = max_length
        self.running = True
        
    def stop(self):
        self.running = False
        
    def run(self):
        total_combinations = 0
        for length in range(self.min_length, self.max_length + 1):
            total_combinations += len(self.char_set) ** length
            
        tried_combinations = 0
        found = False
        
        for length in range(self.min_length, self.max_length + 1):
            if not self.running:
                break
                
            for attempt in itertools.product(self.char_set, repeat=length):
                if not self.running:
                    break
                    
                tried_combinations += 1
                if tried_combinations % 10000 == 0 or tried_combinations == total_combinations:
                    progress = min(100, int((tried_combinations / total_combinations) * 100))
                    current_text = ''.join(attempt)
                    self.update_progress.emit(progress, current_text)
                
                text = ''.join(attempt)
                hashed = get_hash(text, self.hash_type)
                
                if hashed == self.target_hash:
                    self.found_match.emit(text, hashed)
                    # Обеспечиваем достижение 100% прогресса при нахождении совпадения
                    self.update_progress.emit(100, text)
                    found = True
                    break
            
            if found:
                break
        
        # Устанавливаем прогресс в 100% при завершении, если не был найден результат
        if not found and self.running:
            self.update_progress.emit(100, "")
                
        self.finished_task.emit()
    
    def get_hash(self, text):
        return get_hash(text, self.hash_type)

class DictionaryBruteForceWorker(QThread):
    update_progress = pyqtSignal(int, str)
    found_match = pyqtSignal(str, str)
    finished_task = pyqtSignal()
    
    def __init__(self, hash_type, target_hash, dictionary_path):
        super().__init__()
        self.hash_type = hash_type
        self.target_hash = target_hash.lower()
        self.dictionary_path = dictionary_path
        self.running = True
        
    def stop(self):
        self.running = False
        
    def run(self):
        # Сначала посчитаем количество строк в файле для прогресса
        total_lines = 0
        with open(self.dictionary_path, 'r', encoding='utf-8', errors='ignore') as f:
            for _ in f:
                total_lines += 1
                
        tried_combinations = 0
        found = False
        
        with open(self.dictionary_path, 'r', encoding='utf-8', errors='ignore') as f:
            for line in f:
                if not self.running:
                    break
                    
                tried_combinations += 1
                if tried_combinations % 1000 == 0 or tried_combinations == total_lines:
                    progress = min(100, int((tried_combinations / total_lines) * 100))
                    self.update_progress.emit(progress, line.strip())
                
                text = line.strip()
                if not text:  # Пропускаем пустые строки
                    continue
                    
                hashed = get_hash(text, self.hash_type)
                
                if hashed == self.target_hash:
                    self.found_match.emit(text, hashed)
                    # Обеспечиваем достижение 100% прогресса при нахождении совпадения
                    self.update_progress.emit(100, text)
                    found = True
                    break
        
        # Устанавливаем прогресс в 100% при завершении, если не был найден результат
        if not found and self.running:
            self.update_progress.emit(100, "")
                    
        self.finished_task.emit()
    
    def get_hash(self, text):
        return get_hash(text, self.hash_type)

class RainbowTableWorker(QThread):
    update_progress = pyqtSignal(int, str)
    found_match = pyqtSignal(str, str)
    finished_task = pyqtSignal()
    
    def __init__(self, target_hash, rainbow_path):
        super().__init__()
        self.target_hash = target_hash.lower()
        self.rainbow_path = rainbow_path
        self.running = True
        
    def stop(self):
        self.running = False
        
    def run(self):
        # Сначала посчитаем количество строк в файле для прогресса
        total_lines = 0
        with open(self.rainbow_path, 'r', encoding='utf-8', errors='ignore') as f:
            for _ in f:
                total_lines += 1
                
        tried_combinations = 0
        found = False
        
        with open(self.rainbow_path, 'r', encoding='utf-8', errors='ignore') as f:
            for line in f:
                if not self.running:
                    break
                    
                tried_combinations += 1
                if tried_combinations % 1000 == 0 or tried_combinations == total_lines:
                    progress = min(100, int((tried_combinations / total_lines) * 100))
                    self.update_progress.emit(progress, line.strip())
                
                line = line.strip()
                if not line:  # Пропускаем пустые строки
                    continue
                
                # Ожидаем формат файла: хеш:текст
                if ':' not in line:
                    continue
                    
                stored_hash, plaintext = line.split(':', 1)
                stored_hash = stored_hash.lower()
                
                if stored_hash == self.target_hash:
                    self.found_match.emit(plaintext, stored_hash)
                    # Обеспечиваем достижение 100% прогресса при нахождении совпадения
                    self.update_progress.emit(100, plaintext)
                    found = True
                    break
        
        # Устанавливаем прогресс в 100% при завершении, если не был найден результат
        if not found and self.running:
            self.update_progress.emit(100, "")
                    
        self.finished_task.emit()

class HashBruteForcer(QMainWindow):
    def __init__(self):
        super().__init__()
        self.initUI()
        self.worker = None
        
    def initUI(self):
        self.setWindowTitle('Хеш Брутфорсер')
        self.resize(700, 600)
        
        # Main widget and layout
        main_widget = QWidget()
        self.setCentralWidget(main_widget)
        grid = QGridLayout(main_widget)
        
        # Создаем вкладки
        self.tabs = QTabWidget()
        
        # Вкладка для брутфорса перебором
        self.bruteforce_tab = QWidget()
        self.setup_bruteforce_tab()
        self.tabs.addTab(self.bruteforce_tab, "Перебор")
        
        # Вкладка для брутфорса по словарю
        self.dictionary_tab = QWidget()
        self.setup_dictionary_tab()
        self.tabs.addTab(self.dictionary_tab, "Словарь")
        
        # Вкладка для радужных таблиц
        self.rainbow_tab = QWidget()
        self.setup_rainbow_tab()
        self.tabs.addTab(self.rainbow_tab, "Радужные таблицы")
        
        # Вкладка для своего метода хеширования
        self.custom_hash_tab = QWidget()
        self.setup_custom_hash_tab()
        self.tabs.addTab(self.custom_hash_tab, "Свой хеш")
        
        # Hash settings group (общий для всех вкладок)
        hash_group = QGroupBox("Настройки хеша")
        hash_layout = QGridLayout()
        hash_group.setLayout(hash_layout)
        
        # Hash type
        hash_layout.addWidget(QLabel("Тип хеша:"), 0, 0)
        self.hash_type = QComboBox()
        # Получаем все доступные алгоритмы хеширования
        self.hash_type.addItems(get_available_hash_algorithms())
        hash_layout.addWidget(self.hash_type, 0, 1)
        
        # Target hash
        hash_layout.addWidget(QLabel("Целевой хеш:"), 1, 0)
        self.target_hash = QLineEdit()
        hash_layout.addWidget(self.target_hash, 1, 1)
        
        # Control buttons
        control_group = QGroupBox("Управление")
        control_layout = QGridLayout()
        control_group.setLayout(control_layout)
        
        self.start_button = QPushButton("Начать")
        self.start_button.clicked.connect(self.start_bruteforce)
        control_layout.addWidget(self.start_button, 0, 0)
        
        self.stop_button = QPushButton("Остановить")
        self.stop_button.clicked.connect(self.stop_bruteforce)
        self.stop_button.setEnabled(False)
        control_layout.addWidget(self.stop_button, 0, 1)
        
        # Progress
        progress_group = QGroupBox("Прогресс")
        progress_layout = QGridLayout()
        progress_group.setLayout(progress_layout)
        
        self.progress_bar = QProgressBar()
        progress_layout.addWidget(self.progress_bar, 0, 0, 1, 2)
        
        progress_layout.addWidget(QLabel("Текущая комбинация:"), 1, 0)
        self.current_attempt = QLineEdit()
        self.current_attempt.setReadOnly(True)
        progress_layout.addWidget(self.current_attempt, 1, 1)
        
        # Results
        results_group = QGroupBox("Результаты")
        results_layout = QGridLayout()
        results_group.setLayout(results_layout)
        
        self.results = QTextEdit()
        self.results.setReadOnly(True)
        results_layout.addWidget(self.results, 0, 0)
        
        # Add all groups to main layout
        grid.addWidget(self.tabs, 0, 0, 1, 2)
        grid.addWidget(hash_group, 1, 0, 1, 2)
        grid.addWidget(control_group, 2, 0, 1, 2)
        grid.addWidget(progress_group, 3, 0, 1, 2)
        grid.addWidget(results_group, 4, 0, 1, 2)
    
    def setup_bruteforce_tab(self):
        layout = QGridLayout(self.bruteforce_tab)
        
        # Character set group
        charset_group = QGroupBox("Набор символов")
        charset_layout = QGridLayout()
        charset_group.setLayout(charset_layout)
        
        # Character set options
        self.use_lowercase = QCheckBox("Строчные буквы (a-z)")
        self.use_lowercase.setChecked(True)
        charset_layout.addWidget(self.use_lowercase, 0, 0)
        
        self.use_uppercase = QCheckBox("Заглавные буквы (A-Z)")
        charset_layout.addWidget(self.use_uppercase, 1, 0)
        
        self.use_digits = QCheckBox("Цифры (0-9)")
        self.use_digits.setChecked(True)
        charset_layout.addWidget(self.use_digits, 2, 0)
        
        self.use_special = QCheckBox("Специальные символы")
        charset_layout.addWidget(self.use_special, 3, 0)
        
        self.custom_charset = QLineEdit()
        self.custom_charset.setPlaceholderText("Свой набор символов (опционально)")
        charset_layout.addWidget(self.custom_charset, 4, 0, 1, 2)
        
        # Length settings
        length_group = QGroupBox("Длина строки")
        length_layout = QGridLayout()
        length_group.setLayout(length_layout)
        
        length_layout.addWidget(QLabel("Минимальная длина:"), 0, 0)
        self.min_length = QSpinBox()
        self.min_length.setMinimum(1)
        self.min_length.setMaximum(10)
        self.min_length.setValue(1)
        length_layout.addWidget(self.min_length, 0, 1)
        
        length_layout.addWidget(QLabel("Максимальная длина:"), 1, 0)
        self.max_length = QSpinBox()
        self.max_length.setMinimum(1)
        self.max_length.setMaximum(10)
        self.max_length.setValue(4)
        length_layout.addWidget(self.max_length, 1, 1)
        
        layout.addWidget(charset_group, 0, 0)
        layout.addWidget(length_group, 1, 0)
        
    def setup_dictionary_tab(self):
        layout = QGridLayout(self.dictionary_tab)
        
        # Dictionary file selection
        dict_group = QGroupBox("Файл словаря")
        dict_layout = QGridLayout()
        dict_group.setLayout(dict_layout)
        
        dict_layout.addWidget(QLabel("Путь к файлу:"), 0, 0)
        
        # File selection layout
        file_layout = QHBoxLayout()
        
        self.dict_path = QLineEdit()
        self.dict_path.setReadOnly(True)
        self.dict_path.setPlaceholderText("Выберите файл словаря...")
        file_layout.addWidget(self.dict_path)
        
        self.browse_button = QPushButton("Обзор...")
        self.browse_button.clicked.connect(self.browse_dictionary)
        file_layout.addWidget(self.browse_button)
        
        dict_layout.addLayout(file_layout, 0, 1)
        
        # Dictionary options
        self.dict_options_group = QGroupBox("Настройки словаря")
        dict_options_layout = QGridLayout()
        self.dict_options_group.setLayout(dict_options_layout)
        
        self.use_dict_as_is = QCheckBox("Использовать слова как есть")
        self.use_dict_as_is.setChecked(True)
        dict_options_layout.addWidget(self.use_dict_as_is, 0, 0)
        
        # В будущем можно добавить дополнительные опции:
        # - Добавление чисел до/после слова
        # - Использование разных регистров
        # - Замена букв на похожие символы
        
        layout.addWidget(dict_group, 0, 0)
        layout.addWidget(self.dict_options_group, 1, 0)
    
    def setup_rainbow_tab(self):
        layout = QGridLayout(self.rainbow_tab)
        
        # Rainbow table file selection
        rainbow_group = QGroupBox("Файл радужной таблицы")
        rainbow_layout = QGridLayout()
        rainbow_group.setLayout(rainbow_layout)
        
        rainbow_layout.addWidget(QLabel("Путь к файлу:"), 0, 0)
        
        # File selection layout
        file_layout = QHBoxLayout()
        
        self.rainbow_path = QLineEdit()
        self.rainbow_path.setReadOnly(True)
        self.rainbow_path.setPlaceholderText("Выберите файл радужной таблицы...")
        file_layout.addWidget(self.rainbow_path)
        
        self.rainbow_browse_button = QPushButton("Обзор...")
        self.rainbow_browse_button.clicked.connect(self.browse_rainbow)
        file_layout.addWidget(self.rainbow_browse_button)
        
        rainbow_layout.addLayout(file_layout, 0, 1)
        
        # Информация о радужных таблицах
        info_group = QGroupBox("Информация")
        info_layout = QVBoxLayout()
        info_group.setLayout(info_layout)
        
        info_text = QTextEdit()
        info_text.setReadOnly(True)
        info_text.setPlainText(
            "Радужные таблицы - это метод взлома хешей, который использует предварительно вычисленные таблицы для нахождения "
            "исходного текста по его хешу.\n\n"
            "Формат файла радужной таблицы: хеш:исходный_текст (по одной паре на строку).\n\n"
            "Пример:\n"
            "5f4dcc3b5aa765d61d8327deb882cf99:password\n"
            "827ccb0eea8a706c4c34a16891f84e7b:12345"
        )
        info_layout.addWidget(info_text)
        
        layout.addWidget(rainbow_group, 0, 0)
        layout.addWidget(info_group, 1, 0)
    
    def setup_custom_hash_tab(self):
        layout = QVBoxLayout(self.custom_hash_tab)
        
        # Группа для редактора кода хеш-функции
        editor_group = QGroupBox("Редактор кода хеш-функции")
        editor_layout = QVBoxLayout()
        editor_group.setLayout(editor_layout)
        
        # Описание и инструкции
        instructions = QLabel(
            "Введите код для вашей хеш-функции. Функция должна принимать строку и возвращать хеш.\n"
            "Код должен быть отступлен на 4 пробела, так как он будет вставлен в тело функции."
        )
        editor_layout.addWidget(instructions)
        
        # Пример кода
        example_code = QTextEdit()
        example_code.setReadOnly(True)
        example_code.setPlainText(
            "# Пример своей хеш-функции:\n\n"
            "    # Простой хеш-алгоритм, суммирующий ASCII-коды символов\n"
            "    total = 0\n"
            "    for char in text:\n"
            "        total += ord(char)\n"
            "    return hex(total)[2:]  # Преобразуем в hex и убираем '0x'\n\n"
            "# Для использования встроенных алгоритмов можно импортировать hashlib:\n\n"
            "    import hashlib\n"
            "    # Комбинированный хеш MD5 + SHA1\n"
            "    md5 = hashlib.md5(text.encode()).hexdigest()\n"
            "    sha1 = hashlib.sha1(text.encode()).hexdigest()\n"
            "    return md5 + sha1[:10]  # MD5 + первые 10 символов SHA1"
        )
        editor_layout.addWidget(example_code)
        
        # Редактор кода
        editor_layout.addWidget(QLabel("Ваш код хеш-функции:"))
        self.hash_code_editor = QTextEdit()
        self.hash_code_editor.setPlainText("    # Введите код вашей хеш-функции здесь\n    return hashlib.md5(text.encode()).hexdigest()")
        editor_layout.addWidget(self.hash_code_editor)
        
        # Кнопка для загрузки функции
        load_button = QPushButton("Загрузить хеш-функцию")
        load_button.clicked.connect(self.load_custom_hash)
        editor_layout.addWidget(load_button)
        
        # Статус загрузки
        self.hash_status = QLabel("Статус: Не загружено")
        editor_layout.addWidget(self.hash_status)
        
        layout.addWidget(editor_group)
    
    def load_custom_hash(self):
        code = self.hash_code_editor.toPlainText()
        success, message = load_custom_hash_function(code)
        
        if success:
            self.hash_status.setText(f"Статус: {message}")
            # Обновляем список алгоритмов хеширования
            current_algo = self.hash_type.currentText()
            self.hash_type.clear()
            self.hash_type.addItems(get_available_hash_algorithms())
            
            # Попытаемся выбрать "CUSTOM" в списке
            custom_index = self.hash_type.findText("CUSTOM")
            if custom_index >= 0:
                self.hash_type.setCurrentIndex(custom_index)
            else:
                # Если не нашли, пытаемся вернуть предыдущий выбор
                prev_index = self.hash_type.findText(current_algo)
                if prev_index >= 0:
                    self.hash_type.setCurrentIndex(prev_index)
        else:
            self.hash_status.setText(f"Статус: Ошибка загрузки")
            # Показываем сообщение об ошибке
            QMessageBox.critical(self, "Ошибка загрузки хеш-функции", message)
    
    def start_bruteforce(self):
        target_hash = self.target_hash.text().strip()
        if not target_hash:
            self.results.append("Ошибка: введите целевой хеш")
            return
        
        hash_type = self.hash_type.currentText()
        
        # Очистка прогресса и результатов
        self.progress_bar.setValue(0)
        self.current_attempt.clear()
        self.results.clear()
        self.results.append(f"Начало брутфорса для хеша: {target_hash}")
        self.results.append(f"Тип хеша: {hash_type}")
        
        # Проверим какая вкладка активна
        current_tab = self.tabs.currentIndex()
        
        if current_tab == 0:  # Вкладка "Перебор"
            charset = self.get_charset()
            if not charset:
                self.results.append("Ошибка: выберите хотя бы один набор символов")
                return
                
            min_length = self.min_length.value()
            max_length = self.max_length.value()
            
            if min_length > max_length:
                self.results.append("Ошибка: минимальная длина не может быть больше максимальной")
                return
                
            self.results.append(f"Набор символов: {charset}")
            self.results.append(f"Длина: {min_length}-{max_length}")
            self.results.append("Выполнение...")
            
            self.worker = BruteForceWorker(hash_type, target_hash, charset, min_length, max_length)
        
        elif current_tab == 1:  # Вкладка "Словарь"
            dict_path = self.dict_path.text()
            if not dict_path or not os.path.isfile(dict_path):
                self.results.append("Ошибка: выберите корректный файл словаря")
                return
            
            self.results.append(f"Файл словаря: {dict_path}")
            self.results.append("Выполнение...")
            
            self.worker = DictionaryBruteForceWorker(hash_type, target_hash, dict_path)
            
        elif current_tab == 2:  # Вкладка "Радужные таблицы"
            rainbow_path = self.rainbow_path.text()
            if not rainbow_path or not os.path.isfile(rainbow_path):
                self.results.append("Ошибка: выберите корректный файл радужной таблицы")
                return
            
            self.results.append(f"Файл радужной таблицы: {rainbow_path}")
            self.results.append(f"Примечание: для радужных таблиц тип хеша должен соответствовать типу в таблице")
            self.results.append("Выполнение...")
            
            self.worker = RainbowTableWorker(target_hash, rainbow_path)
            
        elif current_tab == 3:  # Вкладка "Свой хеш"
            self.results.append("Ошибка: вкладка 'Свой хеш' используется только для создания хеш-функции")
            self.results.append("Для выполнения брутфорса перейдите на вкладку 'Перебор', 'Словарь' или 'Радужные таблицы'")
            return
        else:
            self.results.append("Ошибка: неизвестная вкладка")
            return
            
        # Подключаем сигналы и запускаем
        self.worker.update_progress.connect(self.update_progress)
        self.worker.found_match.connect(self.found_match)
        self.worker.finished_task.connect(self.finished_task)
        
        self.start_button.setEnabled(False)
        self.stop_button.setEnabled(True)
        
        self.worker.start()
        
    def stop_bruteforce(self):
        if self.worker:
            self.worker.stop()
            self.results.append("Остановлено пользователем")
            
    def update_progress(self, value, current_text):
        self.progress_bar.setValue(value)
        self.current_attempt.setText(current_text)
        
    def found_match(self, text, hashed):
        self.results.append(f"Найдено совпадение!")
        self.results.append(f"Текст: {text}")
        self.results.append(f"Хеш: {hashed}")
        
    def finished_task(self):
        # При завершении задачи убедимся, что прогресс-бар установлен на 100%
        if self.progress_bar.value() < 100:
            self.progress_bar.setValue(100)
            
        self.start_button.setEnabled(True)
        self.stop_button.setEnabled(False)
        self.results.append("Выполнение завершено")

    def get_charset(self):
        charset = ""
        if self.use_lowercase.isChecked():
            charset += string.ascii_lowercase
        if self.use_uppercase.isChecked():
            charset += string.ascii_uppercase
        if self.use_digits.isChecked():
            charset += string.digits
        if self.use_special.isChecked():
            charset += string.punctuation
        
        custom = self.custom_charset.text()
        if custom:
            for char in custom:
                if char not in charset:
                    charset += char
        
        return charset

    def browse_dictionary(self):
        file_path, _ = QFileDialog.getOpenFileName(self, "Выберите файл словаря", "", "Текстовые файлы (*.txt);;Все файлы (*)")
        if file_path:
            self.dict_path.setText(file_path)
    
    def browse_rainbow(self):
        file_path, _ = QFileDialog.getOpenFileName(self, "Выберите файл радужной таблицы", "", "Текстовые файлы (*.txt);;Все файлы (*)")
        if file_path:
            self.rainbow_path.setText(file_path)

# Функции для режима командной строки
def bruteforce_cli(args):
    print(f"Начало брутфорса для хеша: {args.hash}")
    print(f"Тип хеша: {args.type}")
    
    # Определяем набор символов
    if args.charset:
        charset = args.charset
    else:
        charset = ""
        if "a" in args.charset_preset:
            charset += string.ascii_lowercase
        if "A" in args.charset_preset:
            charset += string.ascii_uppercase
        if "0" in args.charset_preset:
            charset += string.digits
        if "!" in args.charset_preset:
            charset += string.punctuation
    
    print(f"Набор символов: {charset}")
    print(f"Длина: {args.min_length}-{args.max_length}")
    print("Выполнение...")
    
    found = False
    total_combinations = 0
    for length in range(args.min_length, args.max_length + 1):
        total_combinations += len(charset) ** length
        
    tried_combinations = 0
    
    for length in range(args.min_length, args.max_length + 1):
        for attempt in itertools.product(charset, repeat=length):
            tried_combinations += 1
            if tried_combinations % 10000 == 0:
                progress = min(100, int((tried_combinations / total_combinations) * 100))
                print(f"Прогресс: {progress}% | Текущая комбинация: {''.join(attempt)}", end="\r")
            
            text = ''.join(attempt)
            hashed = get_hash(text, args.type)
            
            if hashed == args.hash.lower():
                print(f"\nНайдено совпадение!")
                print(f"Текст: {text}")
                print(f"Хеш: {hashed}")
                found = True
                break
        
        if found:
            break
    
    if not found:
        print("\nСовпадений не найдено.")
    
    print("Выполнение завершено")

def dictionary_cli(args):
    print(f"Начало брутфорса по словарю для хеша: {args.hash}")
    print(f"Тип хеша: {args.type}")
    print(f"Файл словаря: {args.dict}")
    print("Выполнение...")
    
    # Сначала посчитаем количество строк в файле для прогресса
    total_lines = 0
    with open(args.dict, 'r', encoding='utf-8', errors='ignore') as f:
        for _ in f:
            total_lines += 1
            
    tried_combinations = 0
    found = False
    
    with open(args.dict, 'r', encoding='utf-8', errors='ignore') as f:
        for line in f:
            tried_combinations += 1
            if tried_combinations % 1000 == 0:
                progress = min(100, int((tried_combinations / total_lines) * 100))
                print(f"Прогресс: {progress}% | Текущая комбинация: {line.strip()}", end="\r")
            
            text = line.strip()
            if not text:  # Пропускаем пустые строки
                continue
                
            hashed = get_hash(text, args.type)
            
            if hashed == args.hash.lower():
                print(f"\nНайдено совпадение!")
                print(f"Текст: {text}")
                print(f"Хеш: {hashed}")
                found = True
                break
    
    if not found:
        print("\nСовпадений не найдено.")
    
    print("Выполнение завершено")

def rainbow_cli(args):
    print(f"Начало поиска по радужной таблице для хеша: {args.hash}")
    print(f"Файл радужной таблицы: {args.rainbow}")
    print("Выполнение...")
    
    # Сначала посчитаем количество строк в файле для прогресса
    total_lines = 0
    with open(args.rainbow, 'r', encoding='utf-8', errors='ignore') as f:
        for _ in f:
            total_lines += 1
            
    tried_combinations = 0
    found = False
    
    with open(args.rainbow, 'r', encoding='utf-8', errors='ignore') as f:
        for line in f:
            tried_combinations += 1
            if tried_combinations % 1000 == 0:
                progress = min(100, int((tried_combinations / total_lines) * 100))
                print(f"Прогресс: {progress}% | Текущая строка: {line.strip()}", end="\r")
            
            line = line.strip()
            if not line:  # Пропускаем пустые строки
                continue
            
            # Ожидаем формат файла: хеш:текст
            if ':' not in line:
                continue
                
            stored_hash, plaintext = line.split(':', 1)
            stored_hash = stored_hash.lower()
            
            if stored_hash == args.hash.lower():
                print(f"\nНайдено совпадение!")
                print(f"Текст: {plaintext}")
                print(f"Хеш: {stored_hash}")
                found = True
                break
    
    if not found:
        print("\nСовпадений не найдено.")
    
    print("Выполнение завершено")

def parse_arguments():
    parser = argparse.ArgumentParser(description='Брутфорс хешей с GUI или командной строкой')
    
    # Основные параметры
    parser.add_argument('-t', '--type', help='Тип хеша (MD5, SHA1, SHA256, и т.д.)', default='MD5')
    parser.add_argument('-H', '--hash', help='Целевой хеш для поиска')
    parser.add_argument('-m', '--mode', choices=['brute', 'dict', 'rainbow', 'gui'], 
                        help='Режим работы: brute (перебор), dict (словарь), rainbow (радужные таблицы), gui (графический интерфейс)', 
                        default='gui')
    
    # Параметры для режима перебора
    parser.add_argument('-c', '--charset', help='Свой набор символов для перебора')
    parser.add_argument('-p', '--charset-preset', help='Набор символов (a - строчные, A - заглавные, 0 - цифры, ! - спецсимволы)', 
                       default='a0')
    parser.add_argument('-min', '--min-length', help='Минимальная длина строки', type=int, default=1)
    parser.add_argument('-max', '--max-length', help='Максимальная длина строки', type=int, default=4)
    
    # Параметры для режима словаря
    parser.add_argument('-d', '--dict', help='Путь к файлу словаря для атаки по словарю')
    
    # Параметры для режима радужных таблиц
    parser.add_argument('-r', '--rainbow', help='Путь к файлу радужной таблицы')
    
    # Параметры для пользовательского хеша
    parser.add_argument('--custom-hash', help='Путь к файлу с пользовательской функцией хеширования')
    
    return parser.parse_args()

def main():
    args = parse_arguments()
    
    # Если указан файл с пользовательской хеш-функцией, загружаем его
    if args.custom_hash and os.path.isfile(args.custom_hash):
        try:
            with open(args.custom_hash, 'r') as f:
                code = f.read()
            success, message = load_custom_hash_function(code)
            if success:
                print(f"Пользовательская хеш-функция загружена: {message}")
                args.type = 'CUSTOM'  # Устанавливаем тип хеша как пользовательский
            else:
                print(f"Ошибка загрузки пользовательской хеш-функции: {message}")
                sys.exit(1)
        except Exception as e:
            print(f"Ошибка при чтении файла с пользовательской хеш-функцией: {str(e)}")
            sys.exit(1)
    
    # Проверяем режим запуска
    if args.mode == 'gui':
        app = QApplication(sys.argv)
        window = HashBruteForcer()
        window.show()
        sys.exit(app.exec_())
    else:
        # Режим командной строки
        if not args.hash:
            print("Ошибка: для командного режима необходимо указать целевой хеш с помощью параметра --hash")
            sys.exit(1)
            
        # Выбираем соответствующую функцию в зависимости от режима
        if args.mode == 'brute':
            bruteforce_cli(args)
        elif args.mode == 'dict':
            if not args.dict:
                print("Ошибка: для режима словаря необходимо указать файл словаря с помощью параметра --dict")
                sys.exit(1)
            dictionary_cli(args)
        elif args.mode == 'rainbow':
            if not args.rainbow:
                print("Ошибка: для режима радужных таблиц необходимо указать файл таблицы с помощью параметра --rainbow")
                sys.exit(1)
            rainbow_cli(args)

if __name__ == '__main__':
    main() 