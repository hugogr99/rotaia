import os
import re
import time
import warnings
import requests
import numpy as np
import pandas as pd
import folium
import streamlit as st
from itertools import combinations
from streamlit_folium import st_folium
from folium.plugins import PolyLineTextPath


warnings.filterwarnings("ignore")
os.environ["OMP_NUM_THREADS"] = "1"
SEED = 42
np.random.seed(SEED)

COR_ROTA = "#dc2626"

# ──────────────────────────────────────────────
# PAGE CONFIG
# ──────────────────────────────────────────────
st.set_page_config(
    page_title="rotaIA",
    page_icon="🗺️",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ──────────────────────────────────────────────
# CSS
# ──────────────────────────────────────────────
st.markdown(
    """
    <style>
    /* Remove os respiros padrão do container principal e usa 100% da largura,
       para o mapa preencher a tela inteira. */
    .block-container {
        padding: 0 !important;
        max-width: 100% !important;
    }
    div.st-key-content_body {
        padding: 0 28px 24px !important;
    }
    /* ── Esconde a faixa branca do header nativo do Streamlit, que ficava
       por cima do mapa tampando o botão de zoom. O botão de recolher a
       sidebar (a setinha «) não estava funcionando de jeito nenhum, então
       foi removido junto — a sidebar agora fica sempre expandida. ── */
    [data-testid="stHeader"] {
        display: none !important;
    }
    [data-testid="stSidebarCollapseButton"],
    [data-testid="stSidebarCollapsedControl"],
    [data-testid="collapsedControl"] {
        display: none !important;
    }
    [data-testid="stAppViewContainer"],
    [data-testid="stMain"] {
        padding-top: 0 !important;
    }
    /* ── SIDEBAR — largura fixa e maior, sem redimensionar. ── */
    section[data-testid="stSidebar"] {
        width: 460px !important;
        min-width: 460px !important;
        max-width: 460px !important;
    }
    section[data-testid="stSidebar"] > div:first-child {
        width: 460px !important;
    }
    [data-testid="stSidebarResizeHandle"] {
        display: none !important;
        pointer-events: none !important;
    }
    /* ── Cards de Distância / Tempo / Paradas — fonte menor pra não
       truncar dentro das colunas estreitas da sidebar (ex: "534.3 …"). ── */
    [data-testid="stMetricValue"] {
        font-size: 1.3rem !important;
        white-space: nowrap !important;
    }
    [data-testid="stMetricLabel"] {
        font-size: 0.72rem !important;
    }
    /* ── RODAPÉ — tudo numa linha só, sempre, não importa a largura da tela. ── */
    .st-key-footer_wrap,
    .st-key-footer_wrap [data-testid="stVerticalBlock"] {
        display: flex !important;
        flex-direction: row !important;
        flex-wrap: nowrap !important;
        align-items: center !important;
        justify-content: center !important;
        gap: 6px !important;
        white-space: nowrap !important;
        overflow-x: auto !important;
        padding: 18px 0 26px !important;
    }
    .st-key-footer_wrap [data-testid="stElementContainer"] {
        width: auto !important;
        flex: 0 0 auto !important;
    }
    .st-key-btn_sobre_criador button {
        background: transparent !important;
        border: none !important;
        box-shadow: none !important;
        color: #dc2626 !important;
        font-weight: 800 !important;
        font-size: 1.3rem !important;
        text-decoration: underline !important;
        padding: 0 !important;
        min-height: 0 !important;
        line-height: 1.4 !important;
        white-space: nowrap !important;
    }
    .st-key-btn_sobre_criador button:hover {
        color: #b91c1c !important;
    }
    </style>
    """,
    unsafe_allow_html=True,
)

# Caminho do logo
_logo_path = os.path.join(os.path.dirname(__file__), "ROTEIRIZADOR_LOGO.png")

def _extract_addr_number(address: str):
    """
    Extrai o número do imóvel a partir do texto digitado pelo usuário
    (ex: 'Avenida Presidente Kennedy, 2299, Osasco, SP' → '2299').
    Necessário porque, em avenidas muito longas, o geocodificador às vezes
    não localiza o número exato e devolve só o nome da rua — nesse caso,
    usamos o número que o próprio usuário digitou em vez de omiti-lo.
    """
    texto = re.sub(r"\b\d{5}-?\d{3}\b", " ", address)  # remove CEPs antes de procurar
    match = re.search(r"(?<!\d)(\d{1,6})(?!\d)", texto)
    return match.group(1) if match else None


# ──────────────────────────────────────────────
# GEOCODING COM CONFIRMAÇÃO — retorna várias opções para o
# usuário escolher a correta (estilo Google Maps), em vez de
# tentar adivinhar sozinho qual é o endereço certo.
# ──────────────────────────────────────────────
def _format_geo_label(props: dict, numero_usuario: str = None) -> str:
    """
    Formata as propriedades de um resultado (Photon ou Nominatim) em um
    endereço legível. Se o serviço não retornar o número do imóvel (comum
    em avenidas longas), usa o número digitado pelo usuário como alternativa.
    """
    linha1 = []
    street = props.get("street")
    housenumber = props.get("housenumber") or numero_usuario
    name = props.get("name")
    if street:
        linha1.append(street)
        if housenumber:
            linha1.append(str(housenumber))
    elif name:
        linha1.append(name)
        if housenumber:
            linha1.append(str(housenumber))

    cidade = (
        props.get("city") or props.get("town") or props.get("village")
        or props.get("district") or props.get("county") or ""
    )
    estado = props.get("state", "")
    pais = props.get("country", "")

    linha2 = ", ".join([p for p in [cidade, estado] if p])
    if pais and pais not in ("Brasil", "Brazil"):
        linha2 = f"{linha2} - {pais}" if linha2 else pais

    partes = [", ".join(linha1) if linha1 else "", linha2]
    label = " - ".join([p for p in partes if p])
    return label or name or "Endereço sem nome"


@st.cache_data(show_spinner=False, ttl=3600)
def _photon_geocode_candidates(address: str, limit: int = 5):
    """Retorna até `limit` candidatos de endereço via Photon, para o usuário confirmar."""
    numero_usuario = _extract_addr_number(address)
    try:
        r = requests.get(
            "https://photon.komoot.io/api/",
            params={"q": address, "limit": limit},
            timeout=10,
            headers={"User-Agent": "roteirizador_tcc_hugogr99/1.0"},
        )
        feats = r.json().get("features", [])
        candidatos = []
        for feat in feats:
            props = feat.get("properties", {})
            c = feat["geometry"]["coordinates"]
            candidatos.append({
                "label": _format_geo_label(props, numero_usuario),
                "lat": c[1],
                "lon": c[0],
            })
        return candidatos
    except Exception:
        return []


@st.cache_data(show_spinner=False, ttl=3600)
def _nominatim_geocode_candidates(address: str, limit: int = 5):
    """Retorna até `limit` candidatos de endereço via Nominatim (fallback), para o usuário confirmar."""
    numero_usuario = _extract_addr_number(address)
    try:
        r = requests.get(
            "https://nominatim.openstreetmap.org/search",
            params={"q": address, "format": "json", "limit": limit, "addressdetails": 1},
            timeout=12,
            headers={"User-Agent": "roteirizador_tcc_hugogr99/1.0"},
        )
        data = r.json()
        candidatos = []
        for item in data:
            addr = item.get("address", {})
            props_like = {
                "street": addr.get("road") or addr.get("street") or addr.get("pedestrian"),
                "housenumber": addr.get("house_number"),
                "name": item.get("display_name", address).split(",")[0],
                "city": addr.get("city") or addr.get("town") or addr.get("village") or addr.get("municipality"),
                "state": addr.get("state"),
                "country": addr.get("country"),
            }
            candidatos.append({
                "label": _format_geo_label(props_like, numero_usuario),
                "lat": float(item["lat"]),
                "lon": float(item["lon"]),
            })
        return candidatos
    except Exception:
        return []


def geocode_candidates(address: str, limit: int = 5):
    """
    Busca candidatos de endereço para o usuário confirmar (Photon primeiro,
    Nominatim como fallback). Não tenta adivinhar sozinho — devolve as
    opções para o usuário escolher a correta. Remove candidatos duplicados
    (mesmo texto formatado) que as APIs às vezes retornam.
    """
    address = address.strip()
    if not address:
        return []
    candidatos = _photon_geocode_candidates(address, limit=limit)
    if not candidatos:
        time.sleep(1.1)
        candidatos = _nominatim_geocode_candidates(address, limit=limit)

    vistos = set()
    unicos = []
    for c in candidatos:
        if c["label"] not in vistos:
            vistos.add(c["label"])
            unicos.append(c)
    return unicos


def _geocode_best(address: str):
    """Geocodifica e devolve só o melhor candidato (usado na primeira tentativa
    automática da importação em massa via CSV/Excel)."""
    address = (address or "").strip()
    if not address:
        return None
    candidatos = geocode_candidates(address, limit=1)
    return candidatos[0] if candidatos else None


# ──────────────────────────────────────────────
# IMPORTAÇÃO DE ENDEREÇOS VIA CSV/EXCEL
# ──────────────────────────────────────────────
CSV_COLS_OBRIGATORIAS = ["rua", "numero", "bairro", "cidade", "estado"]
CSV_COLS_OPCIONAIS    = ["cep"]


def _monta_endereco_csv(row: dict) -> str:
    """Monta uma string de endereço legível a partir das colunas do CSV/Excel
    (rua, numero, bairro, cidade, estado, cep opcional) para geocodificação."""
    def _val(chave):
        v = str(row.get(chave, "") or "").strip()
        return "" if v.lower() == "nan" else v

    linha1 = ", ".join([p for p in [_val("rua"), _val("numero")] if p])
    linha2 = ", ".join([p for p in [_val("bairro"), _val("cidade"), _val("estado")] if p])
    endereco = ", ".join([p for p in [linha1, linha2] if p])
    cep = _val("cep")
    if cep:
        endereco = f"{endereco}, {cep}" if endereco else cep
    return endereco


# ──────────────────────────────────────────────
def haversine(lat1, lon1, lat2, lon2):
    R = 6371
    lat1, lon1, lat2, lon2 = map(np.radians, [lat1, lon1, lat2, lon2])
    dlat, dlon = lat2 - lat1, lon2 - lon1
    a = np.sin(dlat/2)**2 + np.cos(lat1)*np.cos(lat2)*np.sin(dlon/2)**2
    return 2 * R * np.arcsin(np.sqrt(a))


def custo_rota(coords):
    if len(coords) < 2:
        return 0
    lat = np.radians([c[0] for c in coords])
    lon = np.radians([c[1] for c in coords])
    dlat, dlon = np.diff(lat), np.diff(lon)
    a = np.sin(dlat/2)**2 + np.cos(lat[:-1])*np.cos(lat[1:])*np.sin(dlon/2)**2
    return 2 * 6371 * np.sum(np.arcsin(np.sqrt(a)))


# ──────────────────────────────────────────────
# SAVINGS + VND
# ──────────────────────────────────────────────
def rota_cw_savings(coords):
    n = len(coords) - 1
    if n == 0: return [0], 0
    if n == 1: return [0, 1, 0], haversine(*coords[0], *coords[1]) * 2

    idx = list(range(1, n + 1))
    D = np.zeros((n+1, n+1))
    for i in range(n+1):
        for j in range(i+1, n+1):
            d = haversine(coords[i][0], coords[i][1], coords[j][0], coords[j][1])
            D[i,j] = D[j,i] = d

    sav = [(i, j, D[0,i]+D[0,j]-D[i,j]) for i,j in combinations(idx, 2)]
    sav.sort(key=lambda x: x[2], reverse=True)

    rotas = {i: [0, i, 0] for i in idx}
    for i, j, _ in sav:
        ri = next((r for r in rotas.values() if r[1]==i or r[-2]==i), None)
        rj = next((r for r in rotas.values() if r[1]==j or r[-2]==j), None)
        if ri is None or rj is None or ri is rj: continue
        if ri[-2]==i and rj[1]==j:   nova = ri[:-1] + rj[1:]
        elif rj[-2]==j and ri[1]==i: nova = rj[:-1] + ri[1:]
        else: continue
        for k in list(rotas):
            if rotas[k] is ri or rotas[k] is rj: del rotas[k]
        rotas[nova[1]] = nova

    rf   = list(rotas.values())[0]
    dist = sum(D[rf[k], rf[k+1]] for k in range(len(rf)-1))
    return rf, dist


def two_opt(coords):
    m, mc = coords[:], custo_rota(coords)
    for i in range(1, len(coords)-2):
        for j in range(i+2, len(coords)):
            nova = coords[:i] + coords[i:j][::-1] + coords[j:]
            c = custo_rota(nova)
            if c < mc: m, mc = nova, c
    return m

def swap(coords):
    m, mc = coords[:], custo_rota(coords)
    for i in range(1, len(coords)-1):
        for j in range(i+1, len(coords)-1):
            nova = coords[:]
            nova[i], nova[j] = nova[j], nova[i]
            c = custo_rota(nova)
            if c < mc: m, mc = nova, c
    return m

def relocate(coords):
    m, mc = coords[:], custo_rota(coords)
    for i in range(1, len(coords)-1):
        for j in range(1, len(coords)-1):
            if i == j: continue
            nova = coords[:]
            p = nova.pop(i)
            nova.insert(j, p)
            c = custo_rota(nova)
            if c < mc: m, mc = nova, c
    return m

def vnd(coords):
    viz = [two_opt, swap, relocate]
    m, mc = coords[:], custo_rota(coords)
    k = 0
    while k < len(viz):
        nova = viz[k](m)
        c = custo_rota(nova)
        if c < mc: m, mc, k = nova, c, 0
        else: k += 1
    return m, mc


# ──────────────────────────────────────────────
# KMEANS + RL + SAVINGS + VND
# ──────────────────────────────────────────────
def treinar_rl_areas(centros, restaurante, episodes=2000, alpha=0.1, gamma=0.8):
    n = len(centros)
    pts = np.vstack([restaurante, centros])
    Q = {}
    for ep in range(episodes):
        curr, vis = 0, tuple([0])
        while len(vis) <= n:
            state = (curr, vis)
            possiveis = [a for a in range(1, n+1) if a not in vis]
            if not possiveis: break
            if state not in Q: Q[state] = {a: 0.0 for a in possiveis}
            eps_v = max(0.01, 0.2*(1 - ep/episodes))
            action = (np.random.choice(possiveis) if np.random.random() < eps_v
                      else max(Q[state], key=Q[state].get))
            d = haversine(pts[curr][0], pts[curr][1], pts[action][0], pts[action][1])
            reward = -(d**2)
            nv = tuple(sorted(vis + (action,)))
            ns = (action, nv)
            np_ = [a for a in range(1, n+1) if a not in nv]
            mn = 0
            if np_:
                if ns not in Q: Q[ns] = {a: 0.0 for a in np_}
                mn = max(Q[ns].values())
            Q[state][action] += alpha*(reward + gamma*mn - Q[state][action])
            curr, vis = action, nv
    seq, curr, vis = [], 0, tuple([0])
    while len(vis) <= n:
        state = (curr, vis)
        if state not in Q: break
        action = max(Q[state], key=Q[state].get)
        seq.append(action - 1)
        vis = tuple(sorted(vis + (action,)))
        curr = action
    return seq


def rota_hibrida(coords_list: list):
    from sklearn.cluster import KMeans
    inicio   = coords_list[0]
    entregas = coords_list[1:]
    n = len(entregas)
    if n == 0: return [inicio]
    if n == 1: return [inicio, entregas[0]]
    nc = min(6, n)
    km = KMeans(n_clusters=nc, random_state=SEED, n_init=10)
    labels = km.fit_predict(np.array(entregas))
    centros = km.cluster_centers_
    ordem = treinar_rl_areas(centros, np.array(inicio))
    opt = [inicio]
    ref = inicio
    for ai in ordem:
        pts = [e for e, l in zip(entregas, labels) if l == ai]
        if not pts: continue
        loc = [ref] + pts
        idx, _ = rota_cw_savings(loc)
        pre = [loc[i] for i in idx]
        vnd_r, _ = vnd(pre)
        novas = vnd_r[1:]
        if novas and novas[-1] == ref: novas = novas[:-1]
        opt.extend(novas)
        ref = opt[-1]
    opt, _ = vnd(opt)
    return opt


def rota_savings_vnd(coords_list: list):
    idx, _ = rota_cw_savings(coords_list)
    ord_ = [coords_list[i] for i in idx]
    opt, _ = vnd(ord_)
    return opt


# ──────────────────────────────────────────────
# OSRM
# ──────────────────────────────────────────────
def get_osrm_route(lat1, lon1, lat2, lon2):
    url = f"http://router.project-osrm.org/route/v1/driving/{lon1},{lat1};{lon2},{lat2}"
    try:
        r = requests.get(url, params={"overview": "full", "geometries": "geojson"}, timeout=20)
        r.raise_for_status()
        coords = r.json()["routes"][0]["geometry"]["coordinates"]
        return [(lat, lon) for lon, lat in coords]
    except Exception:
        return [(lat1, lon1), (lat2, lon2)]


def build_full_osrm_route(pts):
    if not pts or len(pts) < 2: return pts
    full = []
    for i in range(len(pts)-1):
        seg = get_osrm_route(pts[i][0], pts[i][1], pts[i+1][0], pts[i+1][1])
        full.extend(seg[1:] if i > 0 else seg)
    return full


# ──────────────────────────────────────────────
# MAPA
# ──────────────────────────────────────────────
PIN_ORIGEM = "#16a34a"
PIN_MID    = "#f59e0b"
PIN_FIM    = "#dc2626"


def _add_markers(mapa, coords, labels):
    n = len(coords)
    for i, (coord, label) in enumerate(zip(coords, labels)):
        cor = PIN_ORIGEM if i == 0 else (PIN_FIM if i == n-1 else PIN_MID)
        html = (
            f'<div style="background:{cor};color:#fff;width:24px;height:24px;'
            f'border-radius:50%;display:flex;align-items:center;justify-content:center;'
            f'font-size:11px;font-weight:bold;'
            f'border:2px solid #fff;box-shadow:0 2px 6px rgba(0,0,0,0.3);">{i}</div>'
        )
        folium.Marker(
            location=coord,
            icon=folium.DivIcon(html=html, icon_size=(24, 24), icon_anchor=(12, 12)),
            tooltip=label,
        ).add_to(mapa)


def make_map_vazio():
    return folium.Map(location=(-22.9068, -43.1729), zoom_start=12, tiles="CartoDB Positron")


def make_map_rota(coords, labels):
    m = folium.Map(location=coords[0], zoom_start=13, tiles="CartoDB Positron")
    with st.spinner("Buscando traçado real das vias (OSRM)…"):
        rota_real = build_full_osrm_route(coords)
    linha = folium.PolyLine(rota_real, color=COR_ROTA, weight=4, opacity=0.85).add_to(m)
    try:
        PolyLineTextPath(linha, "➤   ", repeat=True, offset=5,
                         attributes={"fill": COR_ROTA, "font-weight": "bold", "font-size": "14"}).add_to(m)
    except Exception:
        pass
    _add_markers(m, coords, labels)
    return m


# ──────────────────────────────────────────────
# CLIPBOARD (texto simples para copiar via st.code)
# ──────────────────────────────────────────────
def table_to_tsv(coords, labels, distances, durations):
    linhas = ["#\tEndereço\tDistância (km)\tTempo (min)"]
    for i, (coord, label) in enumerate(zip(coords, labels)):
        linhas.append(f"{i}\t{label}\t{distances[i]}\t{durations[i]}")
    return "\n".join(linhas)


# ──────────────────────────────────────────────
# SESSION STATE
# ──────────────────────────────────────────────
_DEFAULTS = {
    "resultado_pronto": False,
    "coords_rota":      None,
    "labels_rota":      None,
    "enderecos_rota":   None,
    "dist_km":          None,
    "tempo_min":        None,
    "list_distances":   None,
    "list_durations":   None,
    "falhas_nomes":     [],
}
for k, v in _DEFAULTS.items():
    if k not in st.session_state:
        st.session_state[k] = v


def reset_state():
    for k, v in _DEFAULTS.items():
        st.session_state[k] = v


def _limpar_tudo():
    """Reseta a origem, todos os endereços de entrega e o resultado da rota
    — deixa o app como se tivesse acabado de abrir. Também fecha o diálogo
    de importação CSV/Excel, caso estivesse (incorretamente) marcado como
    aberto."""
    st.session_state["origem_state"] = {
        "query": "", "candidates": None, "searched": False,
        "confirmed": False, "label": None, "lat": None, "lon": None,
    }
    st.session_state["destinos_list"] = [{
        "id": 0, "query": "", "candidates": None, "searched": False,
        "confirmed": False, "label": None, "lat": None, "lon": None,
    }]
    st.session_state["destino_id_counter"] = 1
    st.session_state["csv_dialog_open"] = False
    reset_state()


# [Confirmação de endereços] estado da origem e da lista de destinos.
if "origem_state" not in st.session_state:
    st.session_state["origem_state"] = {
        "query": "", "candidates": None, "searched": False,
        "confirmed": False, "label": None, "lat": None, "lon": None,
    }
if "destinos_list" not in st.session_state:
    st.session_state["destinos_list"] = [{
        "id": 0, "query": "", "candidates": None, "searched": False,
        "confirmed": False, "label": None, "lat": None, "lon": None,
    }]
if "destino_id_counter" not in st.session_state:
    st.session_state["destino_id_counter"] = 1

# [Importação via CSV/Excel] estado da janela de importação em massa.
if "csv_dialog_open" not in st.session_state:
    st.session_state["csv_dialog_open"] = False
if "csv_step" not in st.session_state:
    st.session_state["csv_step"] = "upload"
if "csv_addresses" not in st.session_state:
    st.session_state["csv_addresses"] = []
if "csv_id_counter" not in st.session_state:
    st.session_state["csv_id_counter"] = 0


# Comprimento máximo de exibição de um endereço confirmado. Trunca com "…"
# (igual ao Google Maps) para todas as caixas ficarem do mesmo tamanho,
# sem precisar de nenhum CSS.
_ADDR_DISPLAY_MAXLEN = 42


def render_address_box(entry: dict, key_prefix: str, placeholder: str, allow_remove: bool = False):
    """
    Renderiza uma caixa de endereço no estilo Google Maps, 100% com
    componentes nativos do Streamlit (st.columns para os botões ficarem
    ao lado, st.success/st.warning para os estados, truncamento em Python
    para todas as caixas ficarem do mesmo tamanho). Nenhum CSS/HTML custom.
    IMPORTANTE: toda ação aqui dentro que causa um rerun (editar, remover,
    buscar, selecionar candidato) também fecha explicitamente o diálogo de
    importação CSV/Excel (csv_dialog_open = False). Isso evita um bug do
    Streamlit onde, se o diálogo de CSV foi fechado pelo "X" nativo (em vez
    do botão "Cancelar" de dentro dele), a flag interna continuava marcada
    como aberta — e a PRÓXIMA interação em qualquer lugar da sidebar
    (mesmo aqui, nas caixas de endereço) reabria o diálogo sem querer.
    """
    if entry["confirmed"]:
        label = entry["label"] or ""
        label_show = label if len(label) <= _ADDR_DISPLAY_MAXLEN else label[: _ADDR_DISPLAY_MAXLEN - 1].rstrip() + "…"

        if allow_remove:
            col_addr, col_edit, col_del = st.columns([6, 1, 1])
        else:
            col_addr, col_edit = st.columns([6, 1])
            col_del = None

        with col_addr:
            st.success(label_show, icon="✅")
        with col_edit:
            if st.button("✎", key=f"{key_prefix}_editar", use_container_width=True, help="Editar endereço"):
                entry["confirmed"] = False
                entry["candidates"] = None
                entry["searched"] = False
                st.session_state["csv_dialog_open"] = False
                st.rerun()
        if allow_remove:
            with col_del:
                if st.button("🗑", key=f"{key_prefix}_remover", use_container_width=True, help="Remover endereço"):
                    st.session_state["destinos_list"] = [
                        d for d in st.session_state["destinos_list"] if d["id"] != entry["id"]
                    ]
                    st.session_state["csv_dialog_open"] = False
                    st.rerun()
        return

    query = st.text_input(
        "Endereço", label_visibility="collapsed",
        value=entry["query"], placeholder=placeholder,
        key=f"{key_prefix}_query",
    )
    entry["query"] = query

    if allow_remove:
        col_buscar, col_del = st.columns([6, 1])
    else:
        col_buscar, col_del = st.container(), None

    with col_buscar:
        buscar = st.button("🔍︎ Buscar endereço", key=f"{key_prefix}_buscar", use_container_width=True)
    if allow_remove:
        with col_del:
            if st.button("🗑", key=f"{key_prefix}_remover2", use_container_width=True, help="Remover endereço"):
                st.session_state["destinos_list"] = [
                    d for d in st.session_state["destinos_list"] if d["id"] != entry["id"]
                ]
                st.session_state["csv_dialog_open"] = False
                st.rerun()

    if buscar:
        if not query.strip():
            st.warning("Digite um endereço para buscar.")
        else:
            with st.spinner("Buscando endereços…"):
                entry["candidates"] = geocode_candidates(query)
            entry["searched"] = True
            st.session_state["csv_dialog_open"] = False
            st.rerun()

    if entry.get("candidates"):
        with st.container(border=True):
            for i, cand in enumerate(entry["candidates"]):
                if st.button(f" ⚲ {cand['label']}", key=f"{key_prefix}_cand_{i}", use_container_width=True):
                    entry["confirmed"] = True
                    entry["label"] = cand["label"]
                    entry["lat"] = cand["lat"]
                    entry["lon"] = cand["lon"]
                    entry["candidates"] = None
                    st.session_state["csv_dialog_open"] = False
                    st.rerun()
    elif entry.get("searched") and not entry.get("candidates"):
        st.warning("Nenhum endereço encontrado. Tente reformular a busca.")


# ──────────────────────────────────────────────
# POPUP "ENTENDA COMO FUNCIONA" — Interativo com Abas (Tabs)
# ──────────────────────────────────────────────
@st.dialog("Como funcionam os algoritmos?", width="large")
def _mostrar_explicacao_algoritmo():
    # Pegamos o modo atual apenas para definir qual aba virá aberta por padrão
    modo_retorno = st.session_state.get("retornar", False)
    
    # Criamos as duas abas na janela
    nome_aba1 = "KMeans + Reinforcement Learning + Savings + VND"
    nome_aba2 = "Savings + VND"
    
    lista_abas = [nome_aba1, nome_aba2]
    
    # Renderiza as abas na tela
    aba_kmeans, aba_savings = st.tabs(lista_abas)
    
    # ─── CONTEÚDO DA ABA 1: KMEANS + RL + SAVINGS + VND ───
    with aba_kmeans:
        col_txt1, col_video1 = st.columns(2)
        
        with col_txt1:
            st.subheader("KMeans + Reinforcement Learning + Savings + VND")
            st.markdown(
                """
                Resolver o Problema de Roteamento de Veículos (VRP) para múltiplos pontos em tempo real é um desafio de alta complexidade computacional (NP-hard). Se tentássemos aplicar o Reinforcement Learning (RL) diretamente em um mapa massivo, o agente sofreria com a **explosão combinatória**: o espaço de estados e ações cresceria exponencialmente, tornando a convergência matemática inviável.
                
                Para contornar isso, minha abordagem adota uma estratégia híbrida:
                
                * **K-Means como Redutor de Dimensionalidade:** O algoritmo agrupa as entregas por proximidade geográfica, **reduzindo drasticamente o espaço de possibilidades do agente de RL** e dividindo o problema em grupos.
                * **Reinforcement Learning (RL) focado:** Com o espaço otimizado pelo K-Means, o agente consegue convergir com eficiência, aprendendo as melhores políticas de decisão e sequenciamento entre cada cluster.
                * **Quebra de Padrões Geométricos Rígidos:** O algoritmo de *Savings* puro tem uma tendência conhecida de gerar rotas em formato de **"arco"** (grandes voltas que retornam à origem no final). Ao integrar o **K-Means + RL**, essa tendência restritiva é quebrada, pois o modelo é forçado a segmentar o espaço primeiro e roteirizar um número menor de pontos, gerando a possibilidade de rotas abertas caso sejam mais eficientes.
                * **Construção e Refinamento Final (Savings + VND):** A heurística de *Savings* cria rotas iniciais para os pontos internos de cada cluster, e o *Variable Neighborhood Descent* (VND) atua como otimizador final, varrendo a solução através de estruturas de vizinhança para quebrar cruzamentos e garantir uma ótima rota final.
                """
            )
            
        with col_video1:
            video_nome1 = "GIF_RL.mp4"
            video_path1 = os.path.join(os.path.dirname(__file__), video_nome1)
            if os.path.exists(video_path1):
                st.video(video_path1, format="video/mp4", autoplay=True, loop=True, muted=True)
            else:
                st.warning(f"Coloque o arquivo `{video_nome1}` na mesma pasta.")

    # ─── CONTEÚDO DA ABA 2: SAVINGS + VND ───
    with aba_savings:
        col_txt2, col_video2 = st.columns(2)
        
        with col_txt2:
            st.subheader("Savings + VND")
            st.markdown(
                """
                Quando o foco é criar uma rota que retorne à origem ao fim, a combinação do algoritmo de **Savings (Clarke e Wright)** com o **VND** se torna a escolha ideal, funcionando através do conceito de ganho marginal e busca local estruturada.
                
                O coração desse algoritmo reside no cálculo analítico da economia de distância:
                
                1. **O Ponto de Partida Isolado:** Inicialmente, cada entrega possui uma rota exclusiva saindo do depósito e retornando a ele. Se tivermos dois clientes, $P_1$ e $P_2$, a distância separada seria o dobro do custo de ida a cada um.
                2. **O Cálculo do Savings:** O algoritmo calcula matematicamente o ganho obtido ao combinar essas duas rotas em uma só (Origem -> P1 -> P2 -> Origem), quantificado pela fórmula:
                """
            )
            
            # Renderiza a fórmula matemática
            st.latex(r"S_{ij} = d(\text{Origem}, P_1) + d(\text{Origem}, P_2) - d(P_1, P_2)")
            
            st.markdown(
                """
                Se a distância da rota combinada for menor que a soma dos trechos isolados, os pontos são unidos de forma aglomerativa.
                
                3. **Lapidação com VND:** Após o *Savings* construir essa solução inicial, o **VND** assume o controle aplicando sistematicamente heurísticas de modificação (como troca de posições e inversão de sub-rotas), garantindo que a rota final fique livre de ineficiências geográficas, loops ou cruzamentos de nós.
                """
            )
            
        with col_video2:
            video_nome2 = "GIF_SAVINGS.mp4"
            video_path2 = os.path.join(os.path.dirname(__file__), video_nome2)
            if os.path.exists(video_path2):
                st.video(video_path2, format="video/mp4", autoplay=True, loop=True, muted=True)
            else:
                st.warning(f"Coloque o arquivo `{video_nome2}` na mesma pasta.")
                
# ──────────────────────────────────────────────
# POPUP DE ALERTA/VALIDAÇÃO
# ──────────────────────────────────────────────
@st.dialog(" ", width="small")
def _mostrar_alerta(mensagem: str):
    st.markdown(
        f"<div style='text-align:center; font-size:1.2rem; font-weight:600; "
        f"color:#991b1b; padding:10px 4px 22px; line-height:1.5;'>⚠️ {mensagem}</div>",
        unsafe_allow_html=True,
    )
    if st.button("Entendi", use_container_width=True, type="primary"):
        st.rerun()


# ──────────────────────────────────────────────
# POPUP "SOBRE O CRIADOR" — foto + bio, aberto ao clicar em "HUGO ROCHA" no rodapé
# ──────────────────────────────────────────────
@st.dialog("Sobre o Criador", width="large")
def _mostrar_sobre_criador():
    col_foto, col_texto = st.columns([1, 2])
    with col_foto:
        foto_path = os.path.join(os.path.dirname(__file__), "HUGO_FOTO.jpg")
        if os.path.exists(foto_path):
            st.image(foto_path, use_container_width=True)
        else:
            st.warning("Coloque o arquivo `HUGO_FOTO.jpg` na mesma pasta do app.py para exibi-lo aqui.")
    with col_texto:
        st.subheader("Hugo Rocha")
        # ════════════════════════════════════════════════════════════
        # >>> BIO DO CRIADOR <<<
        # ════════════════════════════════════════════════════════════
        st.write(
            "Engenheiro Mecatrônico formado pelo Insper com especialização em Data Science e Analytics pela ESALQ-USP, com carreira desenvolvida em áreas estratégicas de Supply Chain, Logística e Inteligência de Dados. Entusiasta de Data Science e sempre inventando uns projetos 🤪."
        )
        st.subheader("Sobre o rotaIA")
        # ════════════════════════════════════════════════════════════
        # >>> PROJETO <<<
        # ════════════════════════════════════════════════════════════
        st.markdown(
            """
            O **rotaIA** nasceu como o produto final do meu Trabalho de Conclusão de Curso (TCC) no MBA em Data Science e Analytics da **ESALQ-USP**. Durante as minhas pesquisas, percebi que os modelos puros de Machine Learning sofriam muito com problemas de convergência computacional quando o volume de entregas subia demais. Para resolver esse gargalo, desenvolvi um modelo híbrido e, a partir dessa inteligência, criei esta aplicação para resolver o clássico *Travelling Salesman Problem* (Problema do Caixeiro Viajante) de forma visual e prática.
            
            A ideia aqui é entregar uma aplicação de roteirização robusta e completa: o usuário consegue simular rotas inteiras em segundos, cruzar coordenadas geográficas complexas e **exportar a rota final otimizada** direto na interface.
            
            Para dar total flexibilidade, a aplicação conta com dois motores algorítmicos que o usuário pode alternar no painel, cada um calibrado para o melhor cenário que estudei no TCC:
            
            * **O Modelo Híbrido (KMeans + RL):** Foi o arranjo mais eficiente do meu estudo para cenários onde a rota **não precisa retornar à origem**. Ele separa as entregas em clusters, faz melhor rota ENTRE CLUSTERS e por fim roteiriza as entregas INTRA CLUSTERS, quebrando aquela tendência formato de "arco".
            * **O Modelo Heurístico (Savings + VND):** É a escolha perfeita para quando a rota **obrigatoriamente precisa voltar ao ponto de partida (depósito)**. Ele calcula a economia marginal de distância analiticamente e fecha circuitos perfeitos de forma instantânea.
            
            Toda a inteligência por trás da aplicação é validada via **OSRM**, calculando as distâncias com base na malha rodoviária real das ruas (e não em linha reta). No fim, o **rotaIA** transforma modelos matemáticos complexos em uma ferramenta intuitiva para quem precisa planejar rotas eficientes no dia a dia.
            """
        )

# ──────────────────────────────────────────────
# CALLBACKS da edição de endereços na importação via CSV/Excel
# ──────────────────────────────────────────────
def _csv_buscar_novamente(addr_id, cand_key):
    input_key = f"csv_edit_input_{addr_id}"
    texto_atual = st.session_state.get(input_key, "")
    st.session_state[cand_key] = geocode_candidates(texto_atual)


def _csv_selecionar_candidato(addr_id, cand, editando_key, cand_key):
    input_key = f"csv_edit_input_{addr_id}"
    texto_atual = st.session_state.get(input_key, "")
    for x in st.session_state["csv_addresses"]:
        if x["id"] == addr_id:
            x["query"] = texto_atual
            x["label"] = cand["label"]
            x["lat"] = cand["lat"]
            x["lon"] = cand["lon"]
            x["status"] = "ok"
    st.session_state[editando_key] = False
    st.session_state.pop(cand_key, None)


# ──────────────────────────────────────────────
# POPUP "IMPORTAR ENDEREÇOS VIA CSV/EXCEL" — upload → revisão (lista + mapa) → subir
# ──────────────────────────────────────────────
@st.dialog("Importar endereços via CSV/Excel", width="large")
def _dialog_importar_csv():
    # ── ETAPA 1: UPLOAD ────────────────────────────────────────────
    if st.session_state["csv_step"] == "upload":
        st.write(
            "Envie um arquivo **.csv** ou **.xlsx** com os endereços de entrega. "
            "O arquivo precisa ter as colunas **rua, numero, bairro, cidade, estado** "
            "e, opcionalmente, **cep**."
        )
        st.caption("Exemplo: rua;numero;bairro;cidade;estado;cep")

        arquivo = st.file_uploader(
            "Selecione ou arraste o arquivo CSV ou Excel (.xlsx) aqui",
            type=["csv", "xlsx"],
            key="csv_uploader",
        )

        if st.button("Cancelar", key="csv_cancelar_upload"):
            st.session_state["csv_dialog_open"] = False
            if "df_carregado" in st.session_state:
                del st.session_state["df_carregado"]
            st.rerun()

        # Se o usuário removeu o arquivo do uploader, limpamos o estado anterior
        if arquivo is None:
            if "df_carregado" in st.session_state:
                del st.session_state["df_carregado"]

        # Se há um arquivo novo e ele ainda não foi processado para o session_state
        if arquivo is not None and "df_carregado" not in st.session_state:
            nome_arquivo = arquivo.name.lower()
            try:
                if nome_arquivo.endswith(".xlsx"):
                    # openpyxl é necessário no ambiente para rodar esta linha
                    df = pd.read_excel(arquivo, dtype=str).fillna("")
                else:
                    try:
                        df = pd.read_csv(arquivo, dtype=str, sep=None, engine="python").fillna("")
                    except Exception:
                        arquivo.seek(0)
                        df = pd.read_csv(arquivo, dtype=str).fillna("")

                # Padroniza as colunas e salva no session_state para não perder no clique do botão
                df.columns = [c.strip().lower() for c in df.columns]
                st.session_state["df_carregado"] = df

            except Exception as e:
                st.error("Não consegui ler o arquivo. Confirme se é um CSV ou Excel (.xlsx) válido.")
                st.caption(f"Erro interno: {e}")
                return

        # Se o DataFrame já foi carregado com sucesso no estado, continua o fluxo
        if "df_carregado" in st.session_state:
            df = st.session_state["df_carregado"]

            faltando = [c for c in CSV_COLS_OBRIGATORIAS if c not in df.columns]
            if faltando:
                st.error(
                    f"Faltam as colunas obrigatórias: {', '.join(faltando)}. "
                    f"Colunas encontradas: {', '.join(df.columns)}."
                )
                # Remove o df inválido para permitir que o usuário envie outro
                del st.session_state["df_carregado"]
                return

            st.success(f"Arquivo lido com sucesso: {len(df)} endereço(s) encontrado(s).")

            if st.button(
                "⚲ Geocodificar endereços", key="csv_geocodificar",
                type="primary", use_container_width=True,
            ):
                enderecos = []
                total = len(df)
                progresso = st.progress(0.0, text="Buscando coordenadas…")
                for i, row in df.iterrows():
                    row_dict = row.to_dict()
                    endereco_txt = _monta_endereco_csv(row_dict)
                    cand = _geocode_best(endereco_txt)
                    st.session_state["csv_id_counter"] += 1
                    enderecos.append({
                        "id": st.session_state["csv_id_counter"],
                        "query": endereco_txt,
                        "label": cand["label"] if cand else (endereco_txt or "Endereço vazio"),
                        "lat": cand["lat"] if cand else None,
                        "lon": cand["lon"] if cand else None,
                        "status": "ok" if cand else "falhou",
                    })
                    progresso.progress((i + 1) / total, text=f"Buscando coordenadas… ({i+1}/{total})")

                # Limpa o DataFrame temporário antes de ir para a próxima tela
                del st.session_state["df_carregado"]

                st.session_state["csv_addresses"] = enderecos
                st.session_state["csv_step"] = "review"
                st.rerun()

    # ── ETAPA 2: REVISÃO (lista numerada + mapa com os pontos) ─────
    else:
        enderecos = st.session_state["csv_addresses"]
        n_ok = sum(1 for e in enderecos if e["status"] == "ok")
        st.write(
            f"**{n_ok} de {len(enderecos)}** endereços encontrados no mapa. "
            "Confira se os pontos batem; edite ou apague o que estiver errado."
        )

        col_lista, col_mapa = st.columns([1.2, 1])

        with col_lista:
            for idx, e in enumerate(enderecos, start=1):
                editando_key = f"csv_editing_{e['id']}"
                cand_key = f"csv_candidates_{e['id']}"
                c_num, c_label, c_edit, c_del = st.columns([0.5, 4, 0.7, 0.7])
                with c_num:
                    st.markdown(f"**{idx}**")
                with c_label:
                    if e["status"] == "ok":
                        st.success(e["label"], icon="✅")
                    else:
                        st.warning(e["label"], icon="⚠️")
                with c_edit:
                    if st.button("✎", key=f"csv_edit_{e['id']}", help="Editar endereço", use_container_width=True):
                        novo_estado = not st.session_state.get(editando_key, False)
                        st.session_state[editando_key] = novo_estado
                        if novo_estado:
                            # começa a edição sem candidatos de uma busca anterior
                            st.session_state.pop(cand_key, None)
                        st.rerun()
                with c_del:
                    if st.button("🗑", key=f"csv_del_{e['id']}", help="Remover", use_container_width=True):
                        st.session_state["csv_addresses"] = [x for x in enderecos if x["id"] != e["id"]]
                        st.session_state.pop(cand_key, None)
                        st.rerun()

                if st.session_state.get(editando_key, False):
                    with st.container(border=True):
                        st.text_input(
                            "Corrigir endereço", value=e["query"],
                            key=f"csv_edit_input_{e['id']}", label_visibility="collapsed",
                        )
                        st.button(
                            "🔍︎ Buscar novamente",
                            key=f"csv_edit_buscar_{e['id']}",
                            on_click=_csv_buscar_novamente,
                            args=(e["id"], cand_key),
                        )

                        candidatos = st.session_state.get(cand_key)
                        if candidatos:
                            for ci, cand in enumerate(candidatos):
                                st.button(
                                    f"⚲ {cand['label']}",
                                    key=f"csv_cand_{e['id']}_{ci}",
                                    use_container_width=True,
                                    on_click=_csv_selecionar_candidato,
                                    args=(e["id"], cand, editando_key, cand_key),
                                )
                        elif candidatos is not None:
                            st.warning("Nenhum endereço encontrado. Tente reformular a busca.")

        with col_mapa:
            pontos = [e for e in enderecos if e["lat"] is not None]
            if pontos:
                m = folium.Map(
                    location=(pontos[0]["lat"], pontos[0]["lon"]),
                    zoom_start=12, tiles="CartoDB Positron",
                )
                for idx, p in enumerate(enderecos, start=1):
                    if p["lat"] is None:
                        continue
                    html = (
                        f'<div style="background:#2563eb;color:#fff;width:24px;height:24px;'
                        f'border-radius:50%;display:flex;align-items:center;justify-content:center;'
                        f'font-size:11px;font-weight:bold;border:2px solid #fff;'
                        f'box-shadow:0 2px 6px rgba(0,0,0,0.3);">{idx}</div>'
                    )
                    folium.Marker(
                        location=(p["lat"], p["lon"]),
                        icon=folium.DivIcon(html=html, icon_size=(24, 24), icon_anchor=(12, 12)),
                        tooltip=p["label"],
                    ).add_to(m)
                st_folium(m, use_container_width=True, height=430, returned_objects=[], key="csv_review_map")
            else:
                st.info("Nenhum endereço foi geocodificado ainda.")

        st.divider()
        col_voltar, col_subir = st.columns([1, 1.4])
        with col_voltar:
            if st.button("‹ Voltar", key="csv_voltar", use_container_width=True):
                st.session_state["csv_step"] = "upload"
                st.rerun()
        with col_subir:
            if st.button(
                "SUBIR ENDEREÇOS", key="csv_subir",
                type="primary", use_container_width=True,
            ):
                validos = [e for e in st.session_state["csv_addresses"] if e["status"] == "ok"]
                for e in validos:
                    # MESMO padrão do botão "+ Adicionar": pega o valor
                    # atual do contador como o novo ID e SÓ DEPOIS
                    # incrementa. Fazer na ordem inversa (incrementar
                    # antes de usar) deixava o contador "parado" no
                    # último ID já usado pela importação — daí o próximo
                    # endereço adicionado manualmente nascia com o MESMO
                    # ID do último importado, e o Streamlit quebrava por
                    # causa da chave de widget duplicada.
                    novo_id = st.session_state["destino_id_counter"]
                    st.session_state["destino_id_counter"] += 1
                    st.session_state["destinos_list"].append({
                        "id": novo_id,
                        "query": e["query"], "candidates": None, "searched": False,
                        "confirmed": True, "label": e["label"], "lat": e["lat"], "lon": e["lon"],
                    })
                # remove a caixa vazia inicial (placeholder) se ainda não tiver sido usada
                st.session_state["destinos_list"] = [
                    d for d in st.session_state["destinos_list"]
                    if d["confirmed"] or d["query"].strip()
                ]
                st.session_state["csv_addresses"] = []
                st.session_state["csv_step"] = "upload"
                st.session_state["csv_dialog_open"] = False
                st.rerun()


# ════════════════════════════════════════════
# SIDEBAR — logo + configuração da rota
# ════════════════════════════════════════════
with st.sidebar:
    if os.path.exists(_logo_path):
        # Logo centralizada via st.columns (estrutural — sempre confiável,
        # independente de qualquer detalhe interno de CSS do Streamlit) e
        # com use_container_width para acompanhar o tamanho da sidebar.
        col_logo_l, col_logo_c, col_logo_r = st.columns([1, 2, 1])
        with col_logo_c:
            st.image(_logo_path, use_container_width=True)

    st.title("rotaIA")
    st.caption("Otimização de rotas · Data Science & Analytics · ESALQ-USP · 2026")
    st.divider()

    st.subheader("Ponto de Origem")
    render_address_box(
        st.session_state["origem_state"],
        key_prefix="origem",
        placeholder="Ex: Rua da Carioca, 10, Rio de Janeiro, RJ",
        allow_remove=False,
    )

    st.divider()

    st.subheader("Endereços de Entrega")
    st.caption("Busque e confirme cada endereço na lista de opções antes de adicionar o próximo.")

    # Lista de endereços com scroll PRÓPRIO (independente do resto da
    # sidebar): a partir de ~5 endereços, o scroll acontece só aqui dentro,
    # e o botão "Criar Rota" / os cards de métrica continuam sempre
    # visíveis sem precisar rolar a sidebar inteira.
    with st.container(height=420):
        for entry in st.session_state["destinos_list"]:
            render_address_box(
                entry,
                key_prefix=f"dest_{entry['id']}",
                placeholder="Ex: Rua Conde de Bonfim, 422, Tijuca, RJ",
                allow_remove=len(st.session_state["destinos_list"]) > 1,
            )

    col_add, col_limpar = st.columns(2)
    with col_add:
        if st.button("+ Adicionar", key="add_destino", use_container_width=True):
            novo_id = st.session_state["destino_id_counter"]
            st.session_state["destino_id_counter"] += 1
            st.session_state["destinos_list"].append({
                "id": novo_id, "query": "", "candidates": None, "searched": False,
                "confirmed": False, "label": None, "lat": None, "lon": None,
            })
            st.session_state["csv_dialog_open"] = False
            st.rerun()
    with col_limpar:
        if st.button("Limpar tudo", key="btn_limpar_tudo", use_container_width=True):
            _limpar_tudo()
            st.rerun()

    if st.button("📄 Importar endereços (CSV/Excel)", key="btn_abrir_csv", use_container_width=True):
        st.session_state["csv_dialog_open"] = True
        st.rerun()

    st.divider()

    retornar = st.checkbox(
        "Retornar ao ponto de origem",
        value=False,
        help="Gera uma rota circular que volta ao ponto de partida.",
        key="retornar",
    )

    st.divider()

    if retornar:
        st.info("**Savings + VND**\n\nClarke-Wright com busca local VND — ciclo fechado.", icon="🧠")
    else:
        st.info(
            "**KMeans + RL + Savings + VND**\n\n"
            "Clusterização → Reinforcement Learning → otimização local — rota aberta.",
            icon="🧠",
        )

    if st.button("🤔 Entenda como funciona", key="btn_entenda_algoritmo", use_container_width=True):
        _mostrar_explicacao_algoritmo()

    st.divider()

    # ── BOTÃO CRIAR ROTA ──────────────────────────────────────────
    if not st.session_state["resultado_pronto"]:
        if st.button("CRIAR ROTA", type="primary", use_container_width=True):

            origem_state = st.session_state["origem_state"]
            destinos_confirmados = [d for d in st.session_state["destinos_list"] if d["confirmed"]]
            destinos_pendentes = [
                d for d in st.session_state["destinos_list"]
                if not d["confirmed"] and d["query"].strip()
            ]

            # --- validações (com popup grande no meio da tela, não um
            # st.warning() escondido lá embaixo da sidebar) ---
            if not origem_state["confirmed"]:
                _mostrar_alerta("Busque e confirme o ponto de origem.")
                st.stop()

            if not destinos_confirmados:
                _mostrar_alerta("Adicione e confirme ao menos um endereço de entrega.")
                st.stop()

            if destinos_pendentes:
                _mostrar_alerta(
                    "Há endereços de entrega não confirmados. Confirme (clicando na "
                    "opção correta) ou remova-os antes de continuar."
                )
                st.stop()

            todos = [origem_state["label"]] + [d["label"] for d in destinos_confirmados]
            all_coords = [(origem_state["lat"], origem_state["lon"])] + [
                (d["lat"], d["lon"]) for d in destinos_confirmados
            ]

            # --- otimização ---
            with st.spinner("Otimizando rota…"):
                if retornar:
                    coords_opt = rota_savings_vnd(all_coords)
                else:
                    coords_opt = rota_hibrida(all_coords)

            # --- labels ---
            labels = []
            for i, coord in enumerate(coords_opt):
                try:
                    idx = all_coords.index(coord)
                    lbl = todos[idx] if idx < len(todos) else f"Parada {i}"
                except ValueError:
                    lbl = f"Parada {i}"
                labels.append(lbl)
            if retornar and len(labels) < len(coords_opt):
                labels.append(todos[0])

            # --- OSRM: distância e tempo por trecho ---
            # Cards (Distância/Tempo est.) e tabela de paradas vêm da MESMA
            # chamada (route/legs), então os números sempre batem entre si.
            with st.spinner("Calculando km e tempo reais (OSRM)…"):
                list_distances = [0.0]
                list_durations = [0]
                cs_opt = ";".join([f"{lon},{lat}" for lat, lon in coords_opt])
                try:
                    url_route = (
                        f"http://router.project-osrm.org/route/v1/driving/{cs_opt}"
                        f"?overview=false&steps=false"
                    )
                    r_route = requests.get(url_route, timeout=20)
                    legs = r_route.json()["routes"][0]["legs"]
                    for leg in legs:
                        l_dist = leg.get("distance", 0) / 1000
                        l_time = leg.get("duration", 0) / 60
                        list_distances.append(round(l_dist, 1))
                        list_durations.append(int(l_time))
                except Exception:
                    for k in range(1, len(coords_opt)):
                        d_hav = haversine(
                            coords_opt[k-1][0], coords_opt[k-1][1],
                            coords_opt[k][0],   coords_opt[k][1],
                        ) * 1.25
                        t_hav = (d_hav / 18) * 60
                        list_distances.append(round(d_hav, 1))
                        list_durations.append(int(t_hav))

                dist_km   = round(sum(list_distances), 1)
                tempo_min = sum(list_durations)

            st.session_state.update({
                "resultado_pronto": True,
                "coords_rota":      coords_opt,
                "labels_rota":      labels,
                "enderecos_rota":   todos,
                "dist_km":          dist_km,
                "tempo_min":        tempo_min,
                "list_distances":   list_distances,
                "list_durations":   list_durations,
            })
            st.session_state["csv_dialog_open"] = False
            st.rerun()

    # ── BOTÃO NOVA ROTA + MÉTRICAS ─────────────────────────────────
    else:
        if st.button("↺ Calcular Nova Rota", use_container_width=True):
            reset_state()
            st.session_state["csv_dialog_open"] = False
            st.rerun()

        dist_km   = st.session_state["dist_km"]
        tempo_min = st.session_state["tempo_min"]
        n_paradas = len(st.session_state["coords_rota"]) - 1

        c1, c2, c3 = st.columns(3)
        c1.metric("Distância", f"{dist_km:.1f} km")
        c2.metric("Tempo est.", f"{int(tempo_min)} min")
        c3.metric("Paradas", n_paradas)

        falhas_nomes = st.session_state.get("falhas_nomes", [])
        if falhas_nomes:
            st.warning(
                "**Endereços não encontrados** (removidos da rota):\n"
                + "\n".join(f"- {f}" for f in falhas_nomes)
            )


# ════════════════════════════════════════════
# GATILHO DO DIÁLOGO DE IMPORTAÇÃO CSV/EXCEL
# ════════════════════════════════════════════
if st.session_state.get("csv_dialog_open", False):
    _dialog_importar_csv()


# ════════════════════════════════════════════
# ÁREA PRINCIPAL — mapa ocupando a tela toda
# ════════════════════════════════════════════
if not st.session_state["resultado_pronto"]:
    st_folium(make_map_vazio(), use_container_width=True, height=900, returned_objects=[])
else:
    coords_opt = st.session_state["coords_rota"]
    labels     = st.session_state["labels_rota"]
    list_dist  = st.session_state["list_distances"]
    list_dur   = st.session_state["list_durations"]

    st_folium(make_map_rota(coords_opt, labels), use_container_width=True, height=900, returned_objects=[])

# A tabela de paradas e o rodapé ficam num container recuado (começando
# depois da sidebar), para não serem cobertos por ela — só o mapa, acima,
# preenche a tela toda de ponta a ponta.
with st.container(key="content_body"):
    if st.session_state["resultado_pronto"]:
        st.divider()
        st.subheader("Sequência de paradas")

        n = len(coords_opt)
        linhas_tabela = []
        for i, (coord, label) in enumerate(zip(coords_opt, labels)):
            marcador = "🟢 Origem" if i == 0 else ("🏁 Fim" if i == n - 1 else str(i))
            linhas_tabela.append({
                "Parada":          marcador,
                "Endereço":        label,
                "Distância (km)":  list_dist[i] if i < len(list_dist) else None,
                "Tempo (min)":     list_dur[i]  if i < len(list_dur)  else None,
            })
        df_paradas = pd.DataFrame(linhas_tabela)
        st.dataframe(df_paradas, hide_index=True, use_container_width=True)

        with st.expander("🗇 Copiar sequência (texto simples)"):
            tsv = table_to_tsv(coords_opt, labels, list_dist, list_dur)
            st.code(tsv, language=None)

    # ──────────────────────────────────────────
    # FOOTER — texto, botão e links numa linha só, sempre (ver CSS
    # .st-key-footer_wrap lá em cima).
    # ──────────────────────────────────────────
    st.divider()
    with st.container(key="footer_wrap"):
        st.markdown(
            "<span style='color:#6b7280; font-size:1.05rem;'>Criado por</span>",
            unsafe_allow_html=True,
        )
        if st.button("HUGO ROCHA", key="btn_sobre_criador"):
            _mostrar_sobre_criador()
        st.markdown(
            "<span style='font-size:1.05rem;'>"
            "· <a href='https://www.linkedin.com/in/hugogrocha' target='_blank' "
            "style='color:#dc2626; font-weight:600; text-decoration:none;'>LinkedIn</a> "
            "· <a href='https://github.com/hugogr99' target='_blank' "
            "style='color:#dc2626; font-weight:600; text-decoration:none;'>GitHub</a>"
            "</span>",
            unsafe_allow_html=True,
        )