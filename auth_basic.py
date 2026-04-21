import hmac

import streamlit as st


def _get_auth_values() -> tuple[str, str]:
    user = str(st.secrets.get("AUTH_USER", "")).strip()
    passwd = str(st.secrets.get("AUTH_PASS", "")).strip()
    return user, passwd


def is_authenticated() -> bool:
    valid_user, _ = _get_auth_values()
    if not valid_user:
        return False
    sess_user = str(st.session_state.get("aptus_login_user", "")).strip()
    return bool(st.session_state.get("aptus_logged_in")) and sess_user == valid_user


def logout() -> None:
    st.session_state["aptus_logged_in"] = False
    st.session_state.pop("aptus_login_user", None)


def require_login() -> None:
    if not is_authenticated():
        st.warning("Faça login para aceder a esta página.")
        st.switch_page("APTUS.py")
        st.stop()


def render_login_form() -> None:
    st.title("APTUS")
    st.subheader("Login")
    valid_user, valid_pass = _get_auth_values()
    if not valid_user or not valid_pass:
        st.error("Configure `AUTH_USER` e `AUTH_PASS` no secrets.toml para ativar o login.")
        st.stop()

    with st.form("aptus_login_form", clear_on_submit=False):
        user_input = st.text_input("Usuário")
        pass_input = st.text_input("Senha", type="password")
        submit = st.form_submit_button("Entrar", use_container_width=True)

    if submit:
        if not (user_input or "").strip() or not (pass_input or ""):
            st.error("Informe usuário e senha.")
            st.stop()
        ok_user = hmac.compare_digest((user_input or "").strip(), valid_user)
        ok_pass = hmac.compare_digest(pass_input or "", valid_pass)
        if ok_user and ok_pass:
            st.session_state["aptus_logged_in"] = True
            st.session_state["aptus_login_user"] = valid_user
            st.success("Login realizado.")
            st.switch_page("pages/1_Recepcao.py")
            st.stop()
        st.error("Usuário ou senha inválidos.")
