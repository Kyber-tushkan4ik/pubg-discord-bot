import os
import random
from datetime import datetime
from PIL import Image, ImageDraw, ImageFont

def generate_victory_card(nickname, kills, damage, output_path="assets/temp_victory.png", template_name=None, match_date=None):
    """
    Генерує зображення 1024x1024 з текстом поверх ігрового фону.
    """
    assets_dir = os.path.join(os.path.dirname(__file__), '../assets')
    template_path = os.path.join(assets_dir, 'victory_card_1.png')
    font_path = os.path.join(assets_dir, 'font.ttf')
    
    if not os.path.exists(template_path):
        template_path = os.path.join(assets_dir, 'victory_card_3.png')

    if not match_date:
        match_date = datetime.now().strftime("%d.%m.%Y")

    try:
        img = Image.open(template_path).convert("RGBA")
        # Якщо картинка не 1024x1024, підганяємо
        if img.size != (1024, 1024):
            img = img.resize((1024, 1024), Image.LANCZOS)
        
        draw = ImageDraw.Draw(img)
        width, height = img.size

        try:
            # Початковий розмір шрифту
            font_size = 45
            font = ImageFont.truetype(font_path, font_size)
            
            # Функція для відмінювання
            def get_kills_text(num):
                if num % 10 == 1 and num % 100 != 11:
                    return f"{num} ВБИВСТВО"
                elif 2 <= num % 10 <= 4 and (num % 100 < 10 or num % 100 >= 20):
                    return f"{num} ВБИВСТВА"
                else:
                    return f"{num} ВБИВСТВ"

            # Формуємо компоненти тексту
            nick_str = str(nickname).strip()
            kills_str = f"{get_kills_text(kills)}"
            date_str = f"{match_date}"

            # Індивідуальний розрахунок для НІКА
            col_w = width // 3
            safe_margin = 30
            max_nick_w = col_w - (safe_margin * 2)
            
            # Початковий шрифт
            base_font_size = 42
            temp_font = ImageFont.truetype(font_path, base_font_size)
            
            # Цикл масштабування
            nick_font_size = base_font_size
            curr_n_bbox = draw.textbbox((0, 0), nick_str, font=temp_font, anchor="ms")
            while (curr_n_bbox[2] - curr_n_bbox[0]) > max_nick_w and nick_font_size > 14:
                nick_font_size -= 2
                temp_font = ImageFont.truetype(font_path, nick_font_size)
                curr_n_bbox = draw.textbbox((0, 0), nick_str, font=temp_font, anchor="ms")
            
            nick_font = temp_font
            font = ImageFont.truetype(font_path, 42) # Шрифт для інших полів

        except:
            font = ImageFont.load_default()
            nick_font = ImageFont.load_default()

        # Колір
        pubg_gold = (235, 210, 150, 255) 
        shadow_color = (0, 0, 0, 240)

        # ПОВЕРТАЄМО НАЗАД (Поділ на 3 рівні колонки)
        col_w = width // 3
        center_y = height - 120
        
        # 1. НІКНЕЙМ (Центр першої третини)
        draw.text((col_w//2 + 2, center_y + 2), nick_str, font=nick_font, fill=shadow_color, anchor="ms")
        draw.text((col_w//2, center_y), nick_str, font=nick_font, fill=pubg_gold, anchor="ms")
        
        # 2. КІЛИ (Центр картинки)
        draw.text((width//2 + 2, center_y + 2), kills_str, font=font, fill=shadow_color, anchor="ms")
        draw.text((width//2, center_y), kills_str, font=font, fill=pubg_gold, anchor="ms")
        
        # 3. ДАТА (Центр останньої третини)
        draw.text((width - col_w//2 + 2, center_y + 2), date_str, font=font, fill=shadow_color, anchor="ms")
        draw.text((width - col_w//2, center_y), date_str, font=font, fill=pubg_gold, anchor="ms")

        img = img.convert("RGB")
        img.save(output_path, "PNG")
        return output_path
    except Exception as e:
        print(f"Error: {e}")
        return None

if __name__ == "__main__":
    # Тестовий запуск
    res = generate_victory_card("KYBER_TUSHKA", 14, 1850.5, "test_certificate.png", match_date="18.04.2026")
    if res: print(f"Certificate generated: {res}")
