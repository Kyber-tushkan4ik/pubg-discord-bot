import os
import random
from datetime import datetime
from PIL import Image, ImageDraw, ImageFont

def generate_victory_card(player_stats, output_path="assets/temp_victory.png", match_date=None):
    """
    Генерує зображення 1024x1024 з текстом поверх ігрового фону.
    player_stats: список словників [{'nick': '...', 'kills': 0, 'dmg': 0}, ...]
    """
    assets_dir = os.path.join(os.path.dirname(__file__), '../assets')
    font_path = os.path.join(assets_dir, 'font.ttf')
    
    # Забезпечуємо, що player_stats - це список
    if isinstance(player_stats, dict):
        player_stats = [player_stats]
    elif not isinstance(player_stats, list):
        # Fallback для старої підтримки (якщо передано рядок)
        player_stats = [{'nick': str(player_stats), 'kills': 0, 'dmg': 0}]

    # Спробуємо знайти будь-який доступний шаблон
    templates = [
        os.path.join(assets_dir, 'victory_card_1.png'),
        os.path.join(assets_dir, 'victory_card_2.png'),
        os.path.join(assets_dir, 'victory_card_3.png')
    ]
    
    template_path = next((t for t in templates if os.path.exists(t)), None)

    if not match_date:
        match_date = datetime.now().strftime("%d.%m.%Y")

    try:
        if template_path:
            img = Image.open(template_path).convert("RGBA")
        else:
            # Створюємо порожній фон, якщо шаблонів взагалі немає
            img = Image.new("RGBA", (1024, 1024), (20, 20, 20, 255))
            draw = ImageDraw.Draw(img)
            draw.rectangle([50, 50, 974, 974], outline=(235, 210, 150, 100), width=5)
        
        # Якщо картинка не 1024x1024, підганяємо
        if img.size != (1024, 1024):
            img = img.resize((1024, 1024), Image.LANCZOS)

        draw = ImageDraw.Draw(img)
        width, height = img.size

        # Кольори
        pubg_gold = (235, 210, 150, 255) 
        shadow_color = (0, 0, 0, 240)
        
        try:
            font_main = ImageFont.truetype(font_path, 40)
            font_small = ImageFont.truetype(font_path, 30)
            font_title = ImageFont.truetype(font_path, 55)
        except:
            font_main = ImageFont.load_default()
            font_small = ImageFont.load_default()
            font_title = ImageFont.load_default()

        if len(player_stats) == 1:
            # Дизайн для одного гравця (класичний)
            p = player_stats[0]
            nick_str = str(p['nick']).strip()
            
            def get_kills_text(num):
                if num % 10 == 1 and num % 100 != 11: return f"{num} ВБИВСТВО"
                elif 2 <= num % 10 <= 4 and (num % 100 < 10 or num % 100 >= 20): return f"{num} ВБИВСТВА"
                else: return f"{num} ВБИВСТВ"
            
            kills_str = get_kills_text(p.get('kills', 0))
            dmg_str = f"{round(p.get('dmg', 0))} ШКОДИ"
            date_str = match_date
            
            col_w = width // 3
            center_y = height - 120
            
            # Нік (Ліворуч)
            draw.text((col_w//2 + 2, center_y + 2), nick_str, font=font_main, fill=shadow_color, anchor="ms")
            draw.text((col_w//2, center_y), nick_str, font=font_main, fill=pubg_gold, anchor="ms")
            
            # Кіли + Шкода (Центр)
            combined_stats = f"{kills_str}  |  {dmg_str}"
            draw.text((width//2 + 2, center_y + 2), combined_stats, font=font_main, fill=shadow_color, anchor="ms")
            draw.text((width//2, center_y), combined_stats, font=font_main, fill=pubg_gold, anchor="ms")
            
            # Дата (Праворуч)
            # draw.text((width - col_w//2 + 2, center_y + 2), date_str, font=font_main, fill=shadow_color, anchor="ms")
            # draw.text((width - col_w//2, center_y), date_str, font=font_main, fill=pubg_gold, anchor="ms")
            
            # Дата знизу маленька
            draw.text((width//2, height - 50), match_date, font=font_small, fill=pubg_gold, anchor="ms")
            
        else:
            # Дизайн для СКВАДУ
            title_text = "ПЕРЕМОГА СКВАДУ"
            draw.text((width//2 + 3, 153), title_text, font=font_title, fill=shadow_color, anchor="ms")
            draw.text((width//2, 150), title_text, font=font_title, fill=pubg_gold, anchor="ms")
            
            # Вираховуємо y-координату для центрування списку
            total_items = len(player_stats)
            line_height = 80
            start_y = height // 2 - ((total_items - 1) * line_height // 2)
            
            for i, p in enumerate(player_stats):
                p_text = f"{p['nick']}  —  💀 {p.get('kills', 0)}  |  🎯 {round(p.get('dmg', 0))}"
                curr_y = start_y + (i * line_height)
                
                # Тінь
                draw.text((width//2 + 2, curr_y + 2), p_text, font=font_main, fill=shadow_color, anchor="ms")
                # Текст
                draw.text((width//2, curr_y), p_text, font=font_main, fill=pubg_gold, anchor="ms")
            
            # Дата знизу
            draw.text((width//2, height - 80), match_date, font=font_small, fill=pubg_gold, anchor="ms")

        img = img.convert("RGB")
        img.save(output_path, "PNG")
        return output_path
    except Exception as e:
        print(f"Error generating card: {e}")
        return None

if __name__ == "__main__":
    # Тестовий запуск
    test_p = [{'nick': 'KYBER_TUSHKA', 'kills': 14, 'dmg': 1850}]
    res = generate_victory_card(test_p, "test_single.png", match_date="20.04.2026")
    if res: print(f"Single card generated: {res}")
