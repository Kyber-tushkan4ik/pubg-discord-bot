import json
import os

def get_config():
    with open('config.json', 'r', encoding='utf-8') as f:
        return json.load(f)

