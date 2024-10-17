import os
from PIL import Image
from moviepy.editor import VideoFileClip
from pydub import AudioSegment
import pandas as pd
from docx2pdf import convert


def convert_file(input_file, output_format):
    file_extension = os.path.splitext(input_file)[1].lower()

    # Конвертация изображений
    if file_extension in ['.png', '.jpg', '.jpeg', '.bmp']:
        img = Image.open(input_file)
        output_file = input_file.rsplit('.', 1)[0] + '.' + output_format
        img.save(output_file)
        print(f"Image converted to {output_format}: {output_file}")

    # Конвертация аудио
    elif file_extension in ['.mp3', '.wav', '.ogg', '.flac']:
        audio = AudioSegment.from_file(input_file)
        output_file = input_file.rsplit('.', 1)[0] + '.' + output_format
        audio.export(output_file, format=output_format)
        print(f"Audio converted to {output_format}: {output_file}")

    # Конвертация видео
    elif file_extension in ['.mp4', '.avi', '.mov', '.mkv']:
        video = VideoFileClip(input_file)
        output_file = input_file.rsplit('.', 1)[0] + '.' + output_format
        video.write_videofile(output_file)
        print(f"Video converted to {output_format}: {output_file}")

    # Конвертация таблиц (Excel, CSV)
    elif file_extension in ['.xls', '.xlsx', '.csv']:
        df = pd.read_excel(input_file) if file_extension in [
            '.xls', '.xlsx'] else pd.read_csv(input_file)
        output_file = input_file.rsplit('.', 1)[0] + '.' + output_format

        if output_format == 'csv':
            df.to_csv(output_file, index=False)
        elif output_format == 'xlsx':
            df.to_excel(output_file, index=False)
        elif output_format == 'pdf':
            from fpdf import FPDF
            pdf = FPDF()
            pdf.add_page()
            pdf.set_font("Arial", size=12)
            for index, row in df.iterrows():
                pdf.cell(200, 10, txt=" | ".join(
                    [str(item) for item in row]), ln=True)
            pdf.output(output_file)

        print(f"Table converted to {output_format}: {output_file}")

    # Конвертация Word в PDF
    elif file_extension == '.docx' and output_format == 'pdf':
        output_file = input_file.rsplit('.', 1)[0] + '.' + output_format
        convert(input_file, output_file)
        print(f"Word document converted to {output_format}: {output_file}")

    else:
        print(f"Conversion from {file_extension} to {
              output_format} is not supported.")


# Пример использования
if __name__ == "__main__":
    print("Supported formats: images (png, jpg, jpeg, bmp), audio (mp3, wav, ogg, flac), video (mp4, avi, mov, mkv), tables (xlsx, csv), docx to pdf")
    input_file = input("Enter the input file path: ")
    output_format = input(
        "Enter the desired output format (e.g., pdf, mp3, png, etc.): ")

    convert_file(input_file, output_format)
