import streamlit as st

from .layout import icon


def sidebar(pages: list, selected, demo: bool) -> None:
    with st.sidebar:
        st.html('<div class="cp-sidebar-label">Enterprise Views</div>')
        for page in pages:
            if page.url_path == selected.url_path:
                with st.container(key="cp_active_page"):
                    st.page_link(page, width="stretch")
            else:
                st.page_link(page, width="stretch")
        label = "DEMO ENVIRONMENT — MOCK DATA" if demo else "POSTGRESQL DATA SOURCE"
        detail = "Fixed synthetic snapshot" if demo else "Reporting provider"
        st.html(
            f'<div class="cp-environment">{icon("database")}<div>'
            f'<strong>{label}</strong><span>{detail}</span></div></div>'
        )


def brand() -> None:
    st.html(f'<div class="cp-brand">{icon("monitoring")}<strong>CommercePulse</strong></div>')
