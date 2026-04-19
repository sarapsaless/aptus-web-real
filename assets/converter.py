from PIL import Image
import os

# Nome da sua logo que está na pasta
entrada = "logo_aptus.png"
saida = "logo_aptus.ico"

if os.path.exists(entrada):
    img = Image.open(entrada)
    # Define tamanhos padrão para ícones do Windows
    icon_sizes = [(16, 16), (32, 32), (48, 48), (64, 64), (128, 128), (255, 255)]
    img.save(saida, sizes=icon_sizes)
    print(f"Sucesso! O arquivo '{saida}' foi criado na pasta.")
else:
    print(f"Erro: O arquivo '{entrada}' não foi encontrado nesta pasta.")