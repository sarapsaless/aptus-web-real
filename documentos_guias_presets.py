"""Presets editáveis para a Guia de Exames: pacotes de exames e laboratórios parceiros.

Altere este ficheiro para acrescentar ou mudar pacotes e locais sem tocar na lógica da app.
"""

from __future__ import annotations

# --- UI: primeiro item = não aplicar preset automaticamente ---
PACOTE_NENHUM = "— Nenhum (editar manualmente) —"

PACOTES_EXAMES: dict[str, str] = {
    "Admissional — modelo": (
        "Hemograma completo\n"
        "Glicemia\n"
        "Tipagem sanguínea / Rh\n"
        "Exame parasitológico de fezes\n"
        "Audiometria\n"
        "Espirometria\n"
        "Acuidade visual\n"
        "Exame clínico ocupacional"
    ),
    "Periódico — modelo": (
        "Hemograma completo\n"
        "Glicemia\n"
        "Audiometria\n"
        "Espirometria\n"
        "Acuidade visual\n"
        "Exame clínico ocupacional"
    ),
    "Retorno ao trabalho — modelo": (
        "Consulta ocupacional\n"
        "Exame clínico"
    ),
}

LAB_NENHUM = "— Nenhum (editar manualmente) —"

LABORATORIOS_PARCEIROS: dict[str, str] = {
    "BIOLAB — Zequinha Araújo": (
        "BIOLAB - ZEQUINHA ARAÚJO - (AV. JATUARANA, 5395 - NOVA FLORESTA)\n"
        "-> HORARIO 07:00 as 09:45."
    ),
    "OFTALMODERME Saúde": (
        "OFTALMODERME SAÚDE - (AV. SETE DE SETEMBRO - ESQ. ESQUINA, R. GETÚLIO VARGAS, "
        "1748 - NOSSA SRA. DAS GRAÇAS, PORTO VELHO - RO, 76801-028)"
    ),
    "ULTRA-MED": (
        "ULTRA-MED - (RUA: PAULO LEAL, 143 - CENTRO)\n"
        "-> HORARIO: 08:00 as 12:00 | 13:00 as 16:00."
    ),
    "Espaço Renovar": (
        "Espaco Renovar (Endereço: Rua Erva Cidreira, 2623 - Cohab)\n"
        "Horario: "
    ),
    "Laboratório DIAC": (
        "Laboratório DIAC (Endereço: R. Quintino Bocaiúva, 1999 - São Cristóvão)\n"
        "-> Horario: segunda a sexta: 07:00 as 13:00 e 15:00 as 16:30. "
        "Aos sábados : 07:00 as 11:00."
    ),
    "LABORATÓRIO BIOMED": (
        "LABORATÓRIO BIOMED - (ESQUINA COM IMIGRANTES - AV. RIO MADEIRA, "
        "4272- RIO MADEIRA, PORTO VELHO- RO, 76821-300)\n"
        "-> HORARIO: 07:00 as 11h | 13:00 as 17:00."
    ),
    "Clínica Mais Saúde — Zona Sul": (
        "Clinica Mais Saúde - Zona Sul (R. Três e Meio, 2371 - Nova Floresta)\n"
        "-> Horario: 7h as 10h | 14h as 17h"
    ),
}


def lista_opcoes_pacotes() -> list[str]:
    return [PACOTE_NENHUM] + list(PACOTES_EXAMES.keys())


def lista_opcoes_laboratorios() -> list[str]:
    return [LAB_NENHUM] + list(LABORATORIOS_PARCEIROS.keys())
