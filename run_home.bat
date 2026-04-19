@echo off
cd /d "%~dp0"
echo APTUS Web (entrada: APTUS.py - abre na Rececao)
echo Pasta: %CD%

if exist ".venv\Scripts\streamlit.exe" (
  echo A usar: .venv\Scripts\streamlit.exe
  ".venv\Scripts\streamlit.exe" run APTUS.py --server.port 8501
) else (
  echo ERRO: Nao existe .venv\Scripts\streamlit.exe
  echo Crie o ambiente: python -m venv .venv
  echo Depois: .venv\Scripts\pip.exe install -r requirements.txt
)

echo.
echo Se apareceu erro em vermelho, copie o texto antes de fechar.
pause
