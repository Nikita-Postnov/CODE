from PIL import Image
from pydub import AudioSegment
from docx2pdf import convert
import os


def convert_file(input_file, output_format):
    ext = os.path.splitext(input_file)[1].lower()

    # Конвертация изображений
    if ext in ['.jpg', '.jpeg', '.png', '.bmp', '.tiff']:
        img = Image.open(input_file)
        output_file = os.path.splitext(input_file)[0] + '.' + output_format
        img.save(output_file)
        print(f"Image converted to {output_file}")

    # Конвертация аудио
    elif ext in ['.mp3', '.wav', '.ogg', '.flac']:
        audio = AudioSegment.from_file(input_file)
        output_file = os.path.splitext(input_file)[0] + '.' + output_format
        audio.export(output_file, format=output_format)
        print(f"Audio converted to {output_file}")

    # Конвертация документов (например, DOCX -> PDF)
    elif ext == '.docx' and output_format == 'pdf':
        output_file = os.path.splitext(input_file)[0] + '.' + output_format
        convert(input_file, output_file)
        print(f"Document converted to {output_file}")

    else:
        print(f"Conversion for {ext} to {output_format} is not supported.")


# Пример использования
convert_file('example.jpg', 'png')  # Конвертация изображения
convert_file('example.mp3', 'wav')  # Конвертация аудио
convert_file('example.docx', 'pdf')  # Конвертация документов
