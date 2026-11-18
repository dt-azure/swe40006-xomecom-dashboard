import streamlit as st

from .filters import data_scope_control
from .layout import icon


def sidebar(pages: list, selected) -> str:
    with st.sidebar:
        st.html('<div class="cp-sidebar-label">Enterprise Views</div>')
        for page in pages:
            if page.url_path == selected.url_path:
                with st.container(key="cp_active_page"):
                    st.page_link(page, width="stretch")
            else:
                st.page_link(page, width="stretch")
        selection = data_scope_control()
        st.html(
            f'<div class="cp-environment">{icon("database")}<div>'
            '<strong>PostgreSQL Gold</strong><span>Warehouse reporting</span></div></div>'
        )
    return selection


def brand() -> None:
    st.html(f'<div class="cp-brand">{icon("monitoring")}<strong>CommercePulse</strong></div>')
