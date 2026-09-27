"""Segredos (senha da câmera, chave do Roboflow) ficam em variáveis do Windows, nunca em arquivo.

Para gravar, no PowerShell:   setx TAPO_SENHA "minha_senha"
"""
import os
import re

_VARIAVEL = re.compile(r"\$\{([A-Z0-9_]+)\}")


def ler_variavel(nome):
    """Variável de ambiente; no Windows, também a gravada pelo setx (vale sem reabrir o terminal)."""
    valor = os.environ.get(nome, "").strip()
    if not valor and os.name == "nt":
        import winreg
        try:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, "Environment") as reg:
                valor = str(winreg.QueryValueEx(reg, nome)[0]).strip()
        except OSError:
            pass
    return valor


def expandir(texto):
    """Troca ${NOME} pelo valor da variável. Ex.: rtsp://${TAPO_USUARIO}:${TAPO_SENHA}@192.168.0.10/stream1"""
    if not isinstance(texto, str):
        return texto

    def trocar(m):
        valor = ler_variavel(m.group(1))
        if not valor:
            raise SystemExit(f"Falta a variável {m.group(1)}. No PowerShell rode:\n"
                             f'    setx {m.group(1)} "valor"\n')
        # usuário/senha dentro de URL: caracteres especiais precisam ser codificados
        from urllib.parse import quote
        return quote(valor, safe="") if texto.startswith("rtsp://") else valor

    return _VARIAVEL.sub(trocar, texto)


def mascarar(fonte):
    """Esconde usuário e senha ao mostrar uma URL rtsp:// no console ou na tela."""
    return re.sub(r"//[^/@]+@", "//***:***@", str(fonte))
