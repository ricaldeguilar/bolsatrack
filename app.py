import sqlite3
import pandas as pd
import numpy as np
import streamlit as st
import yfinance as yf
from datetime import datetime

# 1. Conexión, creación y actualización de tablas en SQLite
def init_db():
    conn = sqlite3.connect("portafolio.db")
    c = conn.cursor()
    
    # --- Tabla Principal de Transacciones ---
    c.execute(
        """
        CREATE TABLE IF NOT EXISTS transacciones (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            empresa TEXT NOT NULL,
            ticker TEXT NOT NULL,
            fecha_compra TEXT NOT NULL,
            precio_compra REAL NOT NULL,
            fecha_venta TEXT,
            precio_venta REAL
        )
    """
    )
    c.execute("PRAGMA table_info(transacciones)")
    columnas = [columna[1] for columna in c.fetchall()]
    if "cantidad" not in columnas:
        c.execute("ALTER TABLE transacciones ADD COLUMN cantidad REAL DEFAULT 1.0")
        
    # --- Tabla de Auditoría ---
    c.execute(
        """
        CREATE TABLE IF NOT EXISTS auditoria (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            fecha_hora TEXT NOT NULL,
            usuario TEXT NOT NULL,
            accion TEXT NOT NULL,
            detalles TEXT NOT NULL
        )
    """
    )
    
    # --- Tabla de Flujo de Capital ---
    c.execute(
        """
        CREATE TABLE IF NOT EXISTS movimientos_capital (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            fecha TEXT NOT NULL,
            tipo TEXT NOT NULL,
            monto REAL NOT NULL,
            detalles TEXT
        )
    """
    )
    
    # --- Tabla de Usuarios ---
    c.execute(
        """
        CREATE TABLE IF NOT EXISTS usuarios (
            username TEXT PRIMARY KEY,
            password TEXT NOT NULL,
            rol TEXT NOT NULL
        )
    """
    )
    c.execute("SELECT COUNT(*) FROM usuarios")
    if c.fetchone()[0] == 0:
        usuarios_iniciales = [
            ("admin", "admin123", "Admin"),
            ("analista", "analista123", "Analista"),
            ("invitado", "invitado123", "Invitado")
        ]
        c.executemany("INSERT INTO usuarios (username, password, rol) VALUES (?, ?, ?)", usuarios_iniciales)
    
    conn.commit()
    conn.close()

init_db()

# --- FUNCIÓN DE AUDITORÍA ---
def registrar_auditoria(usuario, accion, detalles):
    conn = sqlite3.connect("portafolio.db")
    c = conn.cursor()
    fecha_hora = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    c.execute(
        "INSERT INTO auditoria (fecha_hora, usuario, accion, detalles) VALUES (?, ?, ?, ?)",
        (fecha_hora, usuario, accion, detalles)
    )
    conn.commit()
    conn.close()

# --- FUNCIONES DE CÁLCULO DE CAPITAL ---
def obtener_capital_disponible():
    conn = sqlite3.connect("portafolio.db")
    
    df_movs = pd.read_sql_query("SELECT tipo, monto FROM movimientos_capital", conn)
    ingresos = df_movs[df_movs['tipo'].isin(['Depósito/Fondeo', 'Cobro de Dividendo'])]['monto'].sum() if not df_movs.empty else 0.0
    egresos = df_movs[df_movs['tipo'].isin(['Retiro de Capital', 'Pago de Comisión/Fee'])]['monto'].sum() if not df_movs.empty else 0.0
    flujo_neto_manual = ingresos - egresos
    
    df_trans = pd.read_sql_query("SELECT precio_compra, precio_venta, cantidad, fecha_venta FROM transacciones", conn)
    conn.close()
    
    if not df_trans.empty:
        vendidas = df_trans[df_trans['fecha_venta'].notnull()]
        retorno_ventas = (vendidas['precio_venta'] * vendidas['cantidad']).sum() if not vendidas.empty else 0.0
        dinero_gastado_total = (df_trans['precio_compra'] * df_trans['cantidad']).sum()
        capital_disponible = flujo_neto_manual + retorno_ventas - dinero_gastado_total
    else:
        capital_disponible = flujo_neto_manual
        
    return capital_disponible, flujo_neto_manual


# --- AUXILIAR PARA CALCULAR ESTOCÁSTICO ---
def calcular_stoch_str(df, k_period=15, smooth_k=9, d_period=9):
    if df.empty or len(df) < (k_period + smooth_k + d_period):
        return "N/D"

    low_k = df["Low"].rolling(window=k_period).min()
    high_k = df["High"].rolling(window=k_period).max()
    rangos = high_k - low_k

    fast_k = 100 * ((df["Close"] - low_k) / rangos)
    stoch_k = fast_k.rolling(window=smooth_k).mean()
    stoch_d = stoch_k.rolling(window=d_period).mean()

    stoch_k_clean = stoch_k.dropna()
    stoch_d_clean = stoch_d.dropna()

    if len(stoch_k_clean) < 2 or len(stoch_d_clean) < 1:
        return "N/D"

    val_k = float(stoch_k_clean.iloc[-1])
    val_d = float(stoch_d_clean.iloc[-1])
    prev_k = float(stoch_k_clean.iloc[-2])

    if val_k > prev_k:
        flecha = " ↗️"
    elif val_k < prev_k:
        flecha = " ↘️"
    else:
        flecha = " ➡️"

    return f"{val_k:.2f} / {val_d:.2f}{flecha}"


# 2. Función para obtener precio e indicadores Estocásticos (1D y 1S)
def get_stock_data(ticker):
    try:
        tk = yf.Ticker(ticker)
        
        # Datos diarios y semanales
        data_1d = tk.history(period="6mo", interval="1d")
        data_1s = tk.history(period="2y", interval="1wk")

        if data_1d.empty or len(data_1d) < 35:
            return None, "N/D", "N/D"

        precio_actual = float(data_1d["Close"].iloc[-1])

        # Estocástico 1D y Estocástico 1S (Configuración 9, 9, 15)
        stoch_1d_str = calcular_stoch_str(data_1d, k_period=15, smooth_k=9, d_period=9)
        stoch_1s_str = calcular_stoch_str(data_1s, k_period=15, smooth_k=9, d_period=9)

        return round(precio_actual, 2), stoch_1d_str, stoch_1s_str
    except Exception:
        return None, "N/D", "N/D"


# --- FUNCIÓN DE ESTILOS MODIFICADA PARA NÚMEROS REALES ---
def color_ganancia_usd(col):
    styles = []
    for val in col:
        if pd.isna(val) or val == "N/D":
            styles.append('')
        elif isinstance(val, (int, float)):
            if val < 0:
                styles.append('color: #ff4b4b; font-weight: bold;')
            elif val > 0:
                styles.append('color: #00c04b; font-weight: bold;')
            else:
                styles.append('')
        else:
            styles.append('')
    return styles

def color_movimientos(col):
    styles = []
    for val in col:
        val_str = str(val)
        if val_str in ['Depósito/Fondeo', 'Cobro de Dividendo']:
            styles.append('color: #00c04b; font-weight: bold;')
        elif val_str in ['Retiro de Capital', 'Pago de Comisión/Fee']:
            styles.append('color: #ff4b4b; font-weight: bold;')
        else:
            styles.append('')
    return styles


# --- CONFIGURACIÓN DE PÁGINA ---
st.set_page_config(page_title="Dashboard de Inversiones", layout="wide")

# --- SISTEMA DE LOGIN ---
if "logged_in" not in st.session_state:
    st.session_state.logged_in = False
    st.session_state.rol = None
    st.session_state.username = None

if not st.session_state.logged_in:
    st.title("🔒 Iniciar Sesión")
    with st.form("login_form"):
        user_input = st.text_input("Usuario")
        password_input = st.text_input("Contraseña", type="password")
        submitted = st.form_submit_button("Entrar")
        
        if submitted:
            conn = sqlite3.connect("portafolio.db")
            c = conn.cursor()
            c.execute("SELECT password, rol FROM usuarios WHERE username = ?", (user_input,))
            resultado = c.fetchone()
            conn.close()
            
            if resultado and resultado[0] == password_input:
                st.session_state.logged_in = True
                st.session_state.rol = resultado[1]
                st.session_state.username = user_input
                st.success("Acceso concedido. Cargando...")
                st.rerun()
            else:
                st.error("Usuario o contraseña incorrectos.")
    st.stop()


# ==========================================
# CÓDIGO DEL DASHBOARD (SOLO SI HAY SESIÓN)
# ==========================================
st.title("📈 Dashboard de Inversiones")

# --- BARRA LATERAL ---
st.sidebar.markdown(f"👤 **Usuario:** {st.session_state.username} | 🏷️ **Rol:** {st.session_state.rol}")
if st.sidebar.button("Cerrar Sesión"):
    st.session_state.logged_in = False
    st.session_state.rol = None
    st.session_state.username = None
    st.rerun()

st.sidebar.markdown("---")

# SEPARACIÓN EN NAVEGACIÓN
nav_opciones = ["Posiciones Activas", "Resumen Mensual", "Historial de Ventas", "Gestión de Capital"]
if st.session_state.rol == "Admin":
    nav_opciones.extend(["Registro de Auditoría", "Gestión de Usuarios"])

vista = st.sidebar.radio("Navegación", nav_opciones)
st.sidebar.markdown("---")

capital_disponible, _ = obtener_capital_disponible()

# GESTIÓN DE PERMISOS SEGÚN EL ROL
if st.session_state.rol in ["Admin", "Analista"] and vista in ["Posiciones Activas", "Resumen Mensual", "Historial de Ventas", "Gestión de Capital"]:
    
    opciones_menu = ["-- Seleccionar --", "Registrar Nueva Compra", "Cerrar Posición (Vender)", "Registrar Movimiento de Caja"]
    if st.session_state.rol == "Admin":
        opciones_menu.append("Eliminar Registro (Permanente)")

    accion = st.sidebar.selectbox("Acciones Rápidas", opciones_menu)

    # NUEVA COMPRA
    if accion == "Registrar Nueva Compra":
        st.sidebar.header("Registrar Nueva Compra")
        st.sidebar.info(f"💵 Poder de Compra Disponible: **${capital_disponible:,.2f}**")
        
        with st.sidebar.form("trade_form", clear_on_submit=True):
            empresa = st.text_input("Empresa", value="", placeholder="Ej. Microsoft o Bitcoin")
            ticker = st.text_input("Ticker", value="", placeholder="Ej. MSFT o BTC-USD")
            cantidad = st.number_input("Cantidad (Acciones/Cripto)", value=None, step=0.00000001, format="%.8f")
            fecha_compra = st.date_input("Fecha Compra", value=None)
            precio_compra = st.number_input("Precio Compra ($)", value=None, step=0.00000001, format="%.8f")

            if st.form_submit_button("Guardar Compra"):
                if not empresa or not ticker or cantidad is None or fecha_compra is None or precio_compra is None:
                    st.error("Por favor, completa todos los campos.")
                else:
                    monto_total_compra = cantidad * precio_compra
                    
                    conn = sqlite3.connect("portafolio.db")
                    c = conn.cursor()
                    c.execute(
                        "INSERT INTO transacciones (empresa, ticker, cantidad, fecha_compra, precio_compra, fecha_venta, precio_venta) VALUES (?, ?, ?, ?, ?, NULL, NULL)",
                        (empresa, ticker.upper(), cantidad, str(fecha_compra), precio_compra),
                    )
                    conn.commit()
                    conn.close()
                    
                    registrar_auditoria(st.session_state.username, "COMPRA", f"Activo: {empresa} ({ticker.upper()}) | Cant: {cantidad} | Total Gastado: ${monto_total_compra:.2f} | Precio: ${precio_compra}")
                    
                    st.success("Compra registrada.")
                    if monto_total_compra > capital_disponible:
                        st.warning("⚠️ El monto de la compra excedió tu capital libre disponible (Saldo Negativo/Margen).")
                        
                    st.rerun()

    # CERRAR POSICIÓN
    elif accion == "Cerrar Posición (Vender)":
        st.sidebar.header("Cerrar Posición (Vender)")
        conn = sqlite3.connect("portafolio.db")
        df_activas_list = pd.read_sql_query("SELECT id, empresa, ticker, cantidad, precio_compra, fecha_compra FROM transacciones WHERE fecha_venta IS NULL", conn)
        conn.close()

        if not df_activas_list.empty:
            with st.sidebar.form("sell_form", clear_on_submit=True):
                opciones = ["-- Seleccionar posición --"] + df_activas_list.apply(
                    lambda row: f"#{row['id']} | {row['ticker']} | Cant: {row['cantidad']} | Fecha: {row['fecha_compra']} | ${row['precio_compra']:.8f}", axis=1
                ).tolist()
                
                seleccion = st.selectbox("Selecciona la posición a vender", opciones)
                fecha_venta = st.date_input("Fecha de Venta", value=None)
                precio_venta = st.number_input("Precio de Venta ($)", value=None, step=0.00000001, format="%.8f")
                
                if st.form_submit_button("Registrar Venta"):
                    if seleccion == "-- Seleccionar posición --" or fecha_venta is None or precio_venta is None:
                        st.error("Por favor, completa todos los campos.")
                    else:
                        id_transaccion = int(seleccion.split("#")[1].split(" |")[0])
                        
                        fila_orig = df_activas_list[df_activas_list["id"] == id_transaccion].iloc[0]
                        total_recuperado = precio_venta * fila_orig['cantidad']
                        
                        detalles_venta = f"Venta ID {id_transaccion}: {fila_orig['empresa']} ({fila_orig['ticker']}) | Vendida a: ${precio_venta} | Capital Liberado: ${total_recuperado:.2f}"

                        conn = sqlite3.connect("portafolio.db")
                        c = conn.cursor()
                        c.execute("UPDATE transacciones SET fecha_venta = ?, precio_venta = ? WHERE id = ?", (str(fecha_venta), precio_venta, id_transaccion))
                        conn.commit()
                        conn.close()
                        
                        registrar_auditoria(st.session_state.username, "VENTA", detalles_venta)
                        st.success("Posición cerrada. El capital ha vuelto a tu balance.")
                        st.rerun()
        else:
            st.sidebar.info("No tienes posiciones activas para vender.")
            
    # MOVIMIENTO DE CAJA
    elif accion == "Registrar Movimiento de Caja":
        st.sidebar.header("Nuevo Movimiento de Capital")
        st.sidebar.info(f"💵 Efectivo Libre Actual: **${capital_disponible:,.2f}**")
        
        with st.sidebar.form("caja_form", clear_on_submit=True):
            tipo_mov = st.selectbox("Tipo de Operación", [
                "Depósito/Fondeo", 
                "Retiro de Capital", 
                "Cobro de Dividendo", 
                "Pago de Comisión/Fee"
            ])
            monto_mov = st.number_input("Monto ($)", min_value=0.01, step=0.01, value=None)
            fecha_mov = st.date_input("Fecha", value=None)
            detalles_mov = st.text_input("Detalles / Razón (Opcional)", placeholder="Ej. Fondeo quincenal")
            
            if st.form_submit_button("Registrar Movimiento"):
                if monto_mov is None or fecha_mov is None:
                    st.error("Completa el monto y la fecha.")
                else:
                    conn = sqlite3.connect("portafolio.db")
                    c = conn.cursor()
                    c.execute(
                        "INSERT INTO movimientos_capital (fecha, tipo, monto, detalles) VALUES (?, ?, ?, ?)",
                        (str(fecha_mov), tipo_mov, monto_mov, detalles_mov)
                    )
                    conn.commit()
                    conn.close()
                    
                    registrar_auditoria(st.session_state.username, "MOVIMIENTO CAJA", f"Tipo: {tipo_mov} | Monto: ${monto_mov:.2f} | Detalles: {detalles_mov}")
                    st.success("Caja actualizada exitosamente.")
                    st.rerun()

    # ELIMINAR REGISTRO
    elif accion == "Eliminar Registro (Permanente)":
        st.sidebar.header("Eliminar Registro")
        st.sidebar.warning("⚠️ Acción irreversible.")
        
        conn = sqlite3.connect("portafolio.db")
        df_all_list = pd.read_sql_query("SELECT * FROM transacciones", conn)
        conn.close()

        if not df_all_list.empty:
            with st.sidebar.form("delete_form", clear_on_submit=True):
                def format_delete_row(row):
                    estado = "🟢 Activa" if pd.isna(row['fecha_venta']) else f"🔴 Vendida el {row['fecha_venta']}"
                    return f"#{row['id']} | {row['ticker']} | Cant: {row['cantidad']} | Comprada: {row['fecha_compra']} | {estado}"
                    
                opciones_del = ["-- Seleccionar registro --"] + df_all_list.apply(format_delete_row, axis=1).tolist()
                
                seleccion_del = st.selectbox("Selecciona el registro a eliminar", opciones_del)
                
                if st.form_submit_button("🗑️ Eliminar Definitivamente"):
                    if seleccion_del == "-- Seleccionar registro --":
                        st.error("Selecciona un registro válido.")
                    else:
                        id_eliminar = int(seleccion_del.split("#")[1].split(" |")[0])
                        
                        fila_elim = df_all_list[df_all_list["id"] == id_eliminar].iloc[0]
                        detalles_elim = f"Eliminado ID {id_eliminar}: {fila_elim['empresa']} ({fila_elim['ticker']})"
                        
                        conn = sqlite3.connect("portafolio.db")
                        c = conn.cursor()
                        c.execute("DELETE FROM transacciones WHERE id = ?", (id_eliminar,))
                        conn.commit()
                        conn.close()
                        
                        registrar_auditoria(st.session_state.username, "ELIMINACIÓN", detalles_elim)
                        st.success("Registro eliminado correctamente.")
                        st.rerun()
        else:
            st.sidebar.info("La base de datos de operaciones está vacía.")

elif st.session_state.rol == "Invitado" and vista in ["Posiciones Activas", "Resumen Mensual", "Historial de Ventas", "Gestión de Capital"]:
    st.sidebar.info("👀 Estás en Modo Invitado. Permiso de solo lectura.")


# --- ÁREA PRINCIPAL SEGÚN LA VISTA SELECCIONADA ---

if vista == "Posiciones Activas":
    col_title, col_btn = st.columns([4, 1])
    with col_title:
        st.subheader("🟢 Portafolio Actual (Posiciones Abiertas)")
    with col_btn:
        if st.button("🔄 Actualizar Precios"):
            st.rerun()

    conn = sqlite3.connect("portafolio.db")
    df_activas = pd.read_sql_query("SELECT * FROM transacciones WHERE fecha_venta IS NULL", conn)
    conn.close()

    if not df_activas.empty:
        total_capital_gestion = 0.0
        total_capital_actual = 0.0
        
        precios_act, valores_pos, stochs_1d, stochs_1s, ganancias_pct, ganancias_usd = [], [], [], [], [], []
        
        with st.spinner("Consultando precios e indicadores en vivo..."):
            for idx, row in df_activas.iterrows():
                capital_invertido = row["precio_compra"] * row["cantidad"]
                total_capital_gestion += capital_invertido
                
                p_act, stoch_1d, stoch_1s = get_stock_data(row["ticker"])
                if p_act is not None:
                    valor_posicion = p_act * row["cantidad"]
                    total_capital_actual += valor_posicion
                    
                    g_pct = ((p_act - row["precio_compra"]) / row["precio_compra"]) * 100
                    g_usd = (p_act - row["precio_compra"]) * row["cantidad"]
                    
                    # Se guardan como NUMEROS REALES (floats) en la lista para permitir ordenamiento numérico exacto
                    precios_act.append(p_act)
                    valores_pos.append(valor_posicion)
                    stochs_1d.append(stoch_1d)
                    stochs_1s.append(stoch_1s)
                    ganancias_pct.append(g_pct)
                    ganancias_usd.append(g_usd)
                else:
                    total_capital_actual += capital_invertido
                    precios_act.append(np.nan)
                    valores_pos.append(np.nan)
                    stochs_1d.append("N/D")
                    stochs_1s.append("N/D")
                    ganancias_pct.append(np.nan)
                    ganancias_usd.append(np.nan)

        # --- TARJETAS DE MÉTRICAS GLOBALES ---
        balance_cuenta_total = capital_disponible + total_capital_actual
        
        col_m1, col_m2, col_m3 = st.columns(3)
        col_m1.metric("Capital Libre (Poder de Compra)", f"${capital_disponible:,.2f}")
        col_m2.metric("Valor en Inversiones (Activas)", f"${total_capital_actual:,.2f}")
        col_m3.metric("Balance Total (Libre + Inversiones)", f"${balance_cuenta_total:,.2f}")
        st.markdown("---")
        
        # --- TABLA DE POSICIONES ---
        df_activas["Precio Actual"] = precios_act
        df_activas["Valor Posición ($)"] = valores_pos
        df_activas["STOCH 1D (%K/%D)"] = stochs_1d
        df_activas["STOCH 1S (%K/%D)"] = stochs_1s
        df_activas["Ganancia %"] = ganancias_pct
        df_activas["Ganancia ($)"] = ganancias_usd

        columnas_activas = [
            "empresa", "ticker", "cantidad", "Precio Actual", "Valor Posición ($)", 
            "STOCH 1D (%K/%D)", "STOCH 1S (%K/%D)", "Ganancia %", "Ganancia ($)", 
            "fecha_compra", "precio_compra"
        ]
        
        df_final_activas = df_activas[columnas_activas].rename(columns={
            "empresa": "Empresa", "ticker": "Ticker", "cantidad": "Cantidad", 
            "fecha_compra": "Fecha Compra", "precio_compra": "Precio Compra ($)"
        })
        
        # Diccionario de formato visual. Transforma los flotantes para la UI sin afectar el orden
        format_activas = {
            "Precio Actual": lambda x: "N/D" if pd.isna(x) else (f"${x:,.4f}" if x < 1 else f"${x:,.2f}"),
            "Valor Posición ($)": lambda x: "N/D" if pd.isna(x) else f"${x:,.2f}",
            "Ganancia %": lambda x: "N/D" if pd.isna(x) else f"{x:+.2f}%",
            "Ganancia ($)": lambda x: "N/D" if pd.isna(x) else f"${x:+.2f}",
            "Precio Compra ($)": lambda x: "N/D" if pd.isna(x) else f"${x:,.8f}"
        }
        
        styled_df_activas = df_final_activas.style.format(format_activas).apply(color_ganancia_usd, subset=['Ganancia ($)'])
        st.dataframe(styled_df_activas, use_container_width=True)
    else:
        st.metric("Capital Libre (Poder de Compra)", f"${capital_disponible:,.2f}")
        st.info("No hay posiciones activas en este momento.")

elif vista == "Gestión de Capital":
    st.subheader("🏛️ Gestión y Flujo de Capital")
    st.markdown("Administra el dinero líquido de tu portafolio.")
    
    conn = sqlite3.connect("portafolio.db")
    df_movs = pd.read_sql_query("SELECT id, fecha, tipo, monto, detalles FROM movimientos_capital ORDER BY id DESC", conn)
    conn.close()

    ingresos = df_movs[df_movs['tipo'].isin(['Depósito/Fondeo', 'Cobro de Dividendo'])]['monto'].sum() if not df_movs.empty else 0.0
    egresos = df_movs[df_movs['tipo'].isin(['Retiro de Capital', 'Pago de Comisión/Fee'])]['monto'].sum() if not df_movs.empty else 0.0
    
    col1, col2, col3 = st.columns(3)
    col1.metric("Ingresos Históricos (Depósitos)", f"${ingresos:,.2f}")
    col2.metric("Egresos Históricos (Retiros)", f"${egresos:,.2f}")
    col3.metric("Capital Libre Actual", f"${capital_disponible:,.2f}")
    
    st.markdown("---")
    st.markdown("#### Historial de Movimientos de Caja")
    
    if not df_movs.empty:
        df_final_movs = df_movs[["fecha", "tipo", "monto", "detalles"]].rename(columns={
            "fecha": "Fecha", "tipo": "Tipo de Movimiento", "monto": "Monto ($)", "detalles": "Detalles"
        })
        
        format_movs = {
            "Monto ($)": lambda x: "N/D" if pd.isna(x) else f"${x:,.2f}"
        }
        
        styled_movs = df_final_movs.style.format(format_movs).apply(color_movimientos, subset=['Tipo de Movimiento'])
        st.dataframe(styled_movs, use_container_width=True)
    else:
        st.info("No tienes movimientos de capital registrados. Ingresa fondos desde el menú lateral.")

elif vista == "Resumen Mensual":
    st.subheader("📅 Resumen Mensual de Crecimiento y Ganancias")
    
    conn = sqlite3.connect("portafolio.db")
    df_all = pd.read_sql_query("SELECT * FROM transacciones", conn)
    conn.close()

    if not df_all.empty:
        df_all['fecha_compra_dt'] = pd.to_datetime(df_all['fecha_compra'])
        df_all['fecha_venta_dt'] = pd.to_datetime(df_all['fecha_venta'])
        df_all['capital_invertido'] = df_all['precio_compra'] * df_all['cantidad']
        
        df_all['ganancia'] = 0.0
        vendidas_mask = df_all['fecha_venta'].notnull()
        df_all.loc[vendidas_mask, 'ganancia'] = (df_all.loc[vendidas_mask, 'precio_venta'] - df_all.loc[vendidas_mask, 'precio_compra']) * df_all.loc[vendidas_mask, 'cantidad']
        
        start_date = df_all['fecha_compra_dt'].min()
        end_date = pd.Timestamp(datetime.now().date())
        max_venta = df_all['fecha_venta_dt'].max()
        if pd.notna(max_venta) and max_venta > end_date:
            end_date = max_venta
            
        start_month = start_date.replace(day=1)
        months = pd.date_range(start=start_month, end=end_date, freq='MS')
        
        monthly_data = []
        
        with st.spinner("Calculando métricas avanzadas de meses y promedios..."):
            for m in months:
                month_str = m.strftime('%Y-%m')
                next_m = m + pd.offsets.MonthBegin(1)
                
                ventas_mes = df_all[(df_all['fecha_venta_dt'] >= m) & (df_all['fecha_venta_dt'] < next_m)]
                ganancia_mes = ventas_mes['ganancia'].sum()
                operaciones_mes = len(ventas_mes)
                
                days_in_month = pd.date_range(start=m, end=min(next_m - pd.Timedelta(days=1), end_date), freq='D')
                max_cap = 0
                for d in days_in_month:
                    active = df_all[(df_all['fecha_compra_dt'] <= d) & (df_all['fecha_venta_dt'].isnull() | (df_all['fecha_venta_dt'] > d))]
                    cap_d = active['capital_invertido'].sum()
                    if cap_d > max_cap:
                        max_cap = cap_d
                        
                monthly_data.append({
                    'Mes_Año': month_str,
                    'Capital_Maximo': max_cap,
                    'Operaciones_Cerradas': operaciones_mes,
                    'Ganancia_Total': ganancia_mes
                })
                
        if monthly_data:
            df_resumen = pd.DataFrame(monthly_data)
            
            df_resumen['Cap_Ant'] = df_resumen['Capital_Maximo'].shift(1)
            df_resumen['Cap_12m'] = df_resumen['Capital_Maximo'].shift(12)
            
            df_resumen['Crec. MoM ($)'] = df_resumen['Capital_Maximo'] - df_resumen['Cap_Ant']
            df_resumen['Crec. MoM (%)'] = (df_resumen['Crec. MoM ($)'] / df_resumen['Cap_Ant'].replace(0, pd.NA)) * 100
            df_resumen['Crec. MoM (%)'] = df_resumen['Crec. MoM (%)'].replace([np.inf, -np.inf], pd.NA)

            df_resumen['Crec. YoY ($)'] = df_resumen['Capital_Maximo'] - df_resumen['Cap_12m']
            df_resumen['Crec. YoY (%)'] = (df_resumen['Crec. YoY ($)'] / df_resumen['Cap_12m'].replace(0, pd.NA)) * 100
            df_resumen['Crec. YoY (%)'] = df_resumen['Crec. YoY (%)'].replace([np.inf, -np.inf], pd.NA)

            df_resumen['Prom. Cap (12m)'] = df_resumen['Capital_Maximo'].rolling(window=12, min_periods=1).mean()
            df_resumen['Prom. Gan (12m)'] = df_resumen['Ganancia_Total'].rolling(window=12, min_periods=1).mean()
            
            df_resumen['Ganancia vs Cap (%)'] = (df_resumen['Ganancia_Total'] / df_resumen['Capital_Maximo'].replace(0, pd.NA)) * 100
            df_resumen['Prom. Gan vs Cap 12m (%)'] = (df_resumen['Prom. Gan (12m)'] / df_resumen['Prom. Cap (12m)'].replace(0, pd.NA)) * 100

            df_resumen_final = df_resumen[[
                'Mes_Año', 'Capital_Maximo', 'Crec. MoM ($)', 'Crec. MoM (%)',
                'Crec. YoY ($)', 'Crec. YoY (%)', 'Prom. Cap (12m)',
                'Operaciones_Cerradas', 'Ganancia_Total', 'Ganancia vs Cap (%)',
                'Prom. Gan (12m)', 'Prom. Gan vs Cap 12m (%)'
            ]].rename(columns={
                'Mes_Año': 'Mes / Año',
                'Capital_Maximo': 'Capital Máximo',
                'Crec. MoM ($)': 'vs Mes Ant. ($)',
                'Crec. MoM (%)': 'vs Mes Ant. (%)',
                'Crec. YoY ($)': 'vs 12m Ant. ($)',
                'Crec. YoY (%)': 'vs 12m Ant. (%)',
                'Prom. Cap (12m)': 'Prom. Capital (12m)',
                'Operaciones_Cerradas': 'Transacciones Cerradas',
                'Ganancia_Total': 'Ganancia ($)',
                'Prom. Gan (12m)': 'Prom. Ganancia (12m)'
            })
            
            format_resumen = {
                'Capital Máximo': lambda x: "N/D" if pd.isna(x) else f"${x:,.2f}",
                'vs Mes Ant. ($)': lambda x: "N/D" if pd.isna(x) else f"${x:+.2f}",
                'vs Mes Ant. (%)': lambda x: "N/D" if pd.isna(x) else f"{x:+.2f}%",
                'vs 12m Ant. ($)': lambda x: "N/D" if pd.isna(x) else f"${x:+.2f}",
                'vs 12m Ant. (%)': lambda x: "N/D" if pd.isna(x) else f"{x:+.2f}%",
                'Prom. Capital (12m)': lambda x: "N/D" if pd.isna(x) else f"${x:,.2f}",
                'Ganancia ($)': lambda x: "N/D" if pd.isna(x) else f"${x:+.2f}",
                'Ganancia vs Cap (%)': lambda x: "N/D" if pd.isna(x) else f"{x:+.2f}%",
                'Prom. Ganancia (12m)': lambda x: "N/D" if pd.isna(x) else f"${x:+.2f}",
                'Prom. Gan vs Cap 12m (%)': lambda x: "N/D" if pd.isna(x) else f"{x:+.2f}%"
            }
            
            columnas_color = [
                'vs Mes Ant. ($)', 'vs Mes Ant. (%)', 'vs 12m Ant. ($)', 'vs 12m Ant. (%)',
                'Ganancia ($)', 'Ganancia vs Cap (%)', 'Prom. Ganancia (12m)', 'Prom. Gan vs Cap 12m (%)'
            ]
            
            styled_resumen = df_resumen_final.style.format(format_resumen).apply(color_ganancia_usd, subset=columnas_color)
            st.dataframe(styled_resumen, use_container_width=True)
        else:
            st.info("No hay datos calculables para mostrar en el resumen.")
    else:
        st.info("La base de datos está vacía. Registra operaciones para ver el resumen mensual.")

elif vista == "Historial de Ventas":
    st.subheader("🔴 Historial de Ventas (Detalle de Operaciones)")
    conn = sqlite3.connect("portafolio.db")
    df_vendidas = pd.read_sql_query("SELECT * FROM transacciones WHERE fecha_venta IS NOT NULL", conn)
    conn.close()

    if not df_vendidas.empty:
        ganancias_pct, ganancias_usd = [], []
        for idx, row in df_vendidas.iterrows():
            g_pct = ((row["precio_venta"] - row["precio_compra"]) / row["precio_compra"]) * 100
            g_usd = (row["precio_venta"] - row["precio_compra"]) * row["cantidad"]
            ganancias_pct.append(g_pct)
            ganancias_usd.append(g_usd)

        df_vendidas["Ganancia %"] = ganancias_pct
        df_vendidas["Ganancia ($)"] = ganancias_usd
        
        columnas_vendidas = ["empresa", "ticker", "cantidad", "precio_compra", "precio_venta", "Ganancia %", "Ganancia ($)", "fecha_compra", "fecha_venta"]
        df_final_vendidas = df_vendidas[columnas_vendidas].rename(columns={
            "empresa": "Empresa", "ticker": "Ticker", "cantidad": "Cantidad", 
            "precio_compra": "Precio Compra ($)", "precio_venta": "Precio Venta ($)", 
            "fecha_compra": "Fecha Compra", "fecha_venta": "Fecha Venta"
        })
        
        format_ventas = {
            "Precio Compra ($)": lambda x: "N/D" if pd.isna(x) else f"${x:,.8f}",
            "Precio Venta ($)": lambda x: "N/D" if pd.isna(x) else f"${x:,.8f}",
            "Ganancia %": lambda x: "N/D" if pd.isna(x) else f"{x:+.2f}%",
            "Ganancia ($)": lambda x: "N/D" if pd.isna(x) else f"${x:+.2f}"
        }
        
        styled_df_vendidas = df_final_vendidas.style.format(format_ventas).apply(color_ganancia_usd, subset=['Ganancia ($)'])
        st.dataframe(styled_df_vendidas, use_container_width=True)
    else:
        st.info("Aún no se ha registrado ninguna venta.")

# --- VISTA DE AUDITORÍA (SOLO ADMIN) ---
elif vista == "Registro de Auditoría":
    st.subheader("🛡️ Registro de Auditoría del Sistema")
    st.markdown("Historial detallado de todas las acciones operativas realizadas.")
    
    conn = sqlite3.connect("portafolio.db")
    df_audit = pd.read_sql_query("SELECT id, fecha_hora, usuario, accion, detalles FROM auditoria ORDER BY id DESC", conn)
    conn.close()

    if not df_audit.empty:
        df_audit = df_audit.rename(columns={"id": "ID", "fecha_hora": "Fecha y Hora (Local)", "usuario": "Usuario", "accion": "Acción", "detalles": "Detalles"})
        st.dataframe(df_audit, use_container_width=True)
    else:
        st.info("Aún no hay registros de auditoría almacenados.")

# --- VISTA DE GESTIÓN DE USUARIOS (SOLO ADMIN) ---
elif vista == "Gestión de Usuarios":
    st.subheader("👥 Gestión de Usuarios")
    
    conn = sqlite3.connect("portafolio.db")
    df_users = pd.read_sql_query("SELECT username, rol FROM usuarios", conn)
    conn.close()

    col1, col2, col3 = st.columns(3)

    with col1:
        st.markdown("#### ➕ Crear Usuario")
        with st.form("create_user_form", clear_on_submit=True):
            nuevo_user = st.text_input("Nuevo Username")
            nuevo_pass = st.text_input("Contraseña", type="password")
            nuevo_rol = st.selectbox("Rol", ["Admin", "Analista", "Invitado"])
            
            if st.form_submit_button("Crear Usuario"):
                if not nuevo_user or not nuevo_pass:
                    st.error("Ingresa nombre de usuario y contraseña.")
                elif nuevo_user in df_users['username'].values:
                    st.error("El nombre de usuario ya existe.")
                else:
                    conn = sqlite3.connect("portafolio.db")
                    c = conn.cursor()
                    c.execute("INSERT INTO usuarios (username, password, rol) VALUES (?, ?, ?)", (nuevo_user, nuevo_pass, nuevo_rol))
                    conn.commit()
                    conn.close()
                    registrar_auditoria(st.session_state.username, "CREAR USUARIO", f"Creado usuario '{nuevo_user}' con rol '{nuevo_rol}'")
                    st.success(f"Usuario {nuevo_user} creado.")
                    st.rerun()

    with col2:
        st.markdown("#### 🔑 Cambiar Contraseña")
        with st.form("change_pass_form", clear_on_submit=True):
            user_mod = st.selectbox("Selecciona Usuario", df_users['username'].tolist())
            nueva_pass = st.text_input("Nueva Contraseña", type="password")
            
            if st.form_submit_button("Actualizar Contraseña"):
                if not nueva_pass:
                    st.error("Ingresa una nueva contraseña.")
                else:
                    conn = sqlite3.connect("portafolio.db")
                    c = conn.cursor()
                    c.execute("UPDATE usuarios SET password = ? WHERE username = ?", (nueva_pass, user_mod))
                    conn.commit()
                    conn.close()
                    registrar_auditoria(st.session_state.username, "CAMBIAR CONTRASEÑA", f"Actualizada clave del usuario '{user_mod}'")
                    st.success("Contraseña actualizada.")
                    st.rerun()

    with col3:
        st.markdown("#### 🗑️ Eliminar Usuario")
        with st.form("delete_user_form", clear_on_submit=True):
            user_del = st.selectbox("Usuario a Eliminar", df_users['username'].tolist())
            
            if st.form_submit_button("Eliminar Definitivamente"):
                if user_del == st.session_state.username:
                    st.error("No puedes eliminar tu propio usuario actual.")
                else:
                    conn = sqlite3.connect("portafolio.db")
                    c = conn.cursor()
                    c.execute("DELETE FROM usuarios WHERE username = ?", (user_del,))
                    conn.commit()
                    conn.close()
                    registrar_auditoria(st.session_state.username, "ELIMINAR USUARIO", f"Usuario '{user_del}' eliminado.")
                    st.success(f"Usuario {user_del} eliminado.")
                    st.rerun()

    st.markdown("---")
    st.markdown("#### 📋 Usuarios Actuales del Sistema")
    st.dataframe(df_users, use_container_width=True)