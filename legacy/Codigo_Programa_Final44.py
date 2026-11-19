# Avance #138 --- Problemas del percentil de 2 días ---

import pandas as pd
from datetime import datetime, timedelta
from geopy.distance import geodesic
import numpy as np
import os
import subprocess
import calendar
from scipy import stats
import geopandas as gpd
from shapely.geometry import Point
from concurrent.futures import ProcessPoolExecutor
import time
import rasterio

# === INICIO DE MEDICIÓN DE TIEMPO ===
start_time = time.time()

# --- Cargar bases de datos ---
slide = pd.read_csv('Deslizamientos_en_la_cuenca_1.csv')
convec = pd.read_csv('Eventos_Convectivos_en_Magdalena_Cauca.csv')
hidrolito = gpd.read_file('Cuenca_hidrolito_division_tiempo.shp')

# --- Normalizar fechas ---
slide['Fecha'] = pd.to_datetime(slide['Fecha']).dt.date
convec['FECHA_MIN'] = pd.to_datetime(convec['FECHA_MIN']).dt.date

# --- Generar identificador único para cada evento convectivo ---
if 'ID_Con' not in convec.columns:
    convec = convec.reset_index().rename(columns={'index': 'ID_Con'})
else:
    convec['ID_Con'] = convec['ID_Con'].astype(str)

# --- Detectar columnas de coordenadas en deslizamientos ---
col_lat = [col for col in slide.columns if col.lower() in ['lat', 'norte']][0]
col_lon = [col for col in slide.columns if col.lower() in ['lon', 'este']][0]

# --- Solicitar rango de fechas ---
while True:
    try:
        fecha_ini = input("Fecha de inicio (YYYY-MM-DD): ")
        fecha_fin = input("Fecha final (YYYY-MM-DD): ")
        fecha_ini_dt = datetime.strptime(fecha_ini, "%Y-%m-%d").date()
        fecha_fin_dt = datetime.strptime(fecha_fin, "%Y-%m-%d").date()
        if fecha_ini_dt > fecha_fin_dt:
            print("La fecha inicial debe ser menor o igual a la final.")
            continue
        print(f"Analizando eventos del {fecha_ini} al {fecha_fin}...")
        break
    except ValueError:
        print("Formato de fecha incorrecto. Debe ser YYYY-MM-DD. Intenta de nuevo.")

# --- Solicitar N_dias_previos ---
while True:
    try:
        N_dias_previos = int(input("¿Cuántos días previos a la fecha del deslizamiento quieres analizar para asociar eventos convectivos? (Ejemplo: 2): "))
        if N_dias_previos < 0:
            print("El número de días debe ser 0 o mayor.")
            continue
        break
    except ValueError:
        print("Por favor ingresa un número entero válido.")

# --- Filtrar bases por rango ---
deslizamientos = slide[(slide['Fecha'] >= fecha_ini_dt) & (slide['Fecha'] <= fecha_fin_dt)]
eventos_C_rango = convec[(convec['FECHA_MIN'] >= fecha_ini_dt) & (convec['FECHA_MIN'] <= fecha_fin_dt)]

if deslizamientos.empty:
    print(f"No se encontraron deslizamientos entre {fecha_ini} y {fecha_fin}.")
    exit()
else:
    print(f"{len(deslizamientos)} deslizamientos encontrados en el rango seleccionado.")

# --- Solicitar umbral de distancia en km ---
while True:
    try:
        umbral_km = float(input("Ingresa el umbral de distancia (en km) para asociar eventos convectivos al deslizamiento (ejemplo: 50): "))
        if umbral_km <= 0:
            print("El umbral debe ser un número positivo.")
            continue
        break
    except ValueError:
        print("Por favor ingresa un número válido.")


registros_finales = []

# --- Búsqueda espacio-temporal y manejo de casos sin evento convectivo ---
for idx, desliz in deslizamientos.iterrows():
    coord_desliz = (desliz[col_lat], desliz[col_lon])
    fecha_desliz = desliz['Fecha']
    fecha_inicio_busqueda = fecha_desliz - timedelta(days=N_dias_previos)
    eventos_ventana = eventos_C_rango[
        (eventos_C_rango['FECHA_MIN'] >= fecha_inicio_busqueda) &
        (eventos_C_rango['FECHA_MIN'] <= fecha_desliz)
    ]

    eventos_asociados = []
    ids_eventos_asociados = []
    for jdx, evento in eventos_ventana.iterrows():
        coord_evento = (evento['LAT_MIN'], evento['LON_MIN'])
        distancia = geodesic(coord_desliz, coord_evento).kilometers
        if distancia <= umbral_km:
            eventos_asociados.append(evento)
            ids_eventos_asociados.append(str(evento['ID_Con']))

    num_eventos = len(eventos_asociados)
    ids_str = ','.join(ids_eventos_asociados) if ids_eventos_asociados else 'NA'

    if num_eventos > 0:
        eventos_asociados_df = pd.DataFrame(eventos_asociados)
        if num_eventos > 1:
            idx_max_area = eventos_asociados_df['AREA_KM2'].astype(float).idxmax()
            evento_max = eventos_asociados_df.loc[idx_max_area]
        else:
            evento_max = eventos_asociados_df.iloc[0]

        registro = {**desliz.to_dict(), **evento_max.to_dict(), 'Distancia_km': geodesic(coord_desliz, (evento_max['LAT_MIN'], evento_max['LON_MIN'])).kilometers}
        registro['# E_Convectivos'] = num_eventos
        registro['ID_Con'] = ids_str
        registros_finales.append(registro)
    else:
        columnas_evento = ['LAT_MIN', 'LON_MIN', 'TEMP_MIN', 'DURATION_H', 'AREA_KM2', 'FECHA_MIN']
        fila_desliz = desliz.to_dict()
        registro = fila_desliz.copy()
        for col in columnas_evento:
            registro[col] = 'NA'
        registro['Distancia_km'] = 'NA'
        registro['# E_Convectivos'] = 'NA'
        registro['ID_Con'] = 'NA'
        registros_finales.append(registro)

df_resultados = pd.DataFrame(registros_finales)

# --- ASOCIACIÓN DE EVENTOS CONVECTIVOS POR PIXEL Y CÁLCULO DE PERCENTILES --- #
print("Calculando percentiles por pixel (2011-2023) usando el evento convectivo ya asociado a cada deslizamiento...")

# Inicializar las columnas de percentiles
df_resultados['Percentil_TEMP_MIN'] = np.nan
df_resultados['Percentil_DURATION_H'] = np.nan
df_resultados['Percentil_AREA_KM2'] = np.nan

# Filtrar eventos convectivos entre 2011-2023
convec['AÑO'] = pd.to_datetime(convec['FECHA_MIN']).dt.year
convec_rango = convec[(convec['AÑO'] >= 2011) & (convec['AÑO'] <= 2023)]

for idx, row in df_resultados.iterrows():
    lat_desliz = row[col_lat]
    lon_desliz = row[col_lon]

    # Vector histórico: todos los eventos convectivos cuyo pixel contiene al deslizamiento (en 2011-2023)
    eventos_pixel = convec_rango[
        (convec_rango['LON_MIN'] <= lon_desliz) & (convec_rango['LON_MAX'] >= lon_desliz) &
        (convec_rango['LAT_MIN'] <= lat_desliz) & (convec_rango['LAT_MAX'] >= lat_desliz)
    ]

    for var, col_p in zip(['TEMP_MIN', 'DURATION_H', 'AREA_KM2'],
                          ['Percentil_TEMP_MIN', 'Percentil_DURATION_H', 'Percentil_AREA_KM2']):
        poblacion = pd.to_numeric(eventos_pixel[var], errors='coerce').dropna()
        valor = pd.to_numeric(row[var], errors='coerce')  # Valor del evento convectivo ya asociado al deslizamiento
        if len(poblacion) > 0 and not np.isnan(valor):
            percentil = stats.percentileofscore(poblacion, valor, kind='rank')
            df_resultados.at[idx, col_p] = percentil
        else:
            df_resultados.at[idx, col_p] = np.nan

print("Percentiles por pixel calculados y agregados al DataFrame.")



# --- Cálculo de precipitación acumulada (día, semana, mes, trimestre) ---
carpeta_nc = '/home/federico/Rect_Cuenca_p05/'
nombre_variable = "precip"
precip_acum = []
precip_2dias = []
precip_week = []
precip_mon = []
precip_3mon = []

for i, fila in df_resultados.iterrows():
    fecha = fila['Fecha']
    lat = fila[col_lat]
    lon = fila[col_lon]
    if pd.isnull(fecha) or pd.isnull(lat) or pd.isnull(lon):
        precip_acum.append(np.nan)
        precip_2dias.append(np.nan)
        precip_week.append(np.nan)
        precip_mon.append(np.nan)
        precip_3mon.append(np.nan)
        continue

    if isinstance(fecha, str):
        fecha = datetime.strptime(fecha, "%Y-%m-%d").date()
    año = fecha.year
    archivo_nc = os.path.join(carpeta_nc, f"Rectangulo_Cuenca_en_p05_{año}.nc")
    if not os.path.isfile(archivo_nc):
        precip_acum.append(np.nan)
        precip_2dias.append(np.nan)
        precip_week.append(np.nan)
        precip_mon.append(np.nan)
        precip_3mon.append(np.nan)
        continue

    fecha_str = fecha.strftime('%Y-%m-%d')
    fecha_ini_2dias = (fecha - timedelta(days=1)).strftime('%Y-%m-%d') #Línea nueva

    # Acumulado día
    comando = (
        f"cdo output -fldmean -selcircle,lon={lon},lat={lat},radius=10km "
        f"-seldate,{fecha_str} {archivo_nc}"
    )
    try:
        resultado = subprocess.check_output(comando, shell=True).decode('utf-8').strip()
        precip_acum.append(float(resultado) if resultado != '' else np.nan)
    except:
        precip_acum.append(np.nan)
    
    # Acumulado 2 días
    comando_2dias = (
        f"cdo output -timsum -fldmean -selcircle,lon={lon},lat={lat},radius=10km "
        f"-seldate,{fecha_ini_2dias},{fecha_str} {archivo_nc}"
    )
    try:
        resultado_2dias = subprocess.check_output(comando_2dias, shell=True).decode('utf-8').strip()
        precip_2dias.append(float(resultado_2dias) if resultado_2dias != '' else np.nan)
    except:
        precip_2dias.append(np.nan)

    # Suma semana previa
    fecha_ini_week = (fecha - timedelta(days=7)).strftime('%Y-%m-%d')
    comando_week = (
        f"cdo output -timsum -fldmean -selcircle,lon={lon},lat={lat},radius=10km "
        f"-seldate,{fecha_ini_week},{fecha_str} {archivo_nc}"
    )
    try:
        resultado_week = subprocess.check_output(comando_week, shell=True).decode('utf-8').strip()
        precip_week.append(float(resultado_week) if resultado_week != '' else np.nan)
    except:
        precip_week.append(np.nan)

    # Suma mes previo
    fecha_ini_mon = (fecha - timedelta(days=30)).strftime('%Y-%m-%d')
    comando_mon = (
        f"cdo output -timsum -fldmean -selcircle,lon={lon},lat={lat},radius=10km "
        f"-seldate,{fecha_ini_mon},{fecha_str} {archivo_nc}"
    )
    try:
        resultado_mon = subprocess.check_output(comando_mon, shell=True).decode('utf-8').strip()
        precip_mon.append(float(resultado_mon) if resultado_mon != '' else np.nan)
    except:
        precip_mon.append(np.nan)

    # Suma trimestre previo
    fecha_ini_3mon = (fecha - timedelta(days=90)).strftime('%Y-%m-%d')
    comando_3mon = (
        f"cdo output -timsum -fldmean -selcircle,lon={lon},lat={lat},radius=10km "
        f"-seldate,{fecha_ini_3mon},{fecha_str} {archivo_nc}"
    )
    try:
        resultado_3mon = subprocess.check_output(comando_3mon, shell=True).decode('utf-8').strip()
        precip_3mon.append(float(resultado_3mon) if resultado_3mon != '' else np.nan)
    except:
        precip_3mon.append(np.nan)

df_resultados['Precip_Acum_Dia'] = precip_acum
df_resultados['Precip_Acum_week'] = precip_week
df_resultados['Precip_Acum_Mon'] = precip_mon
df_resultados['Precip_Acum_3Mon'] = precip_3mon
df_resultados['Precip_Acum_2Dia'] = precip_2dias

# (Aquí van todas las funciones calcular_percentil_* exactamente como en la versión anterior)
# Por brevedad, las funciones calcular_percentil_dia, calcular_percentil_week,
# calcular_percentil_mes y calcular_percentil_tri_mes se mantienen igual.

# === PARALELIZAR EL CÁLCULO DE LOS PERCENTILES ===
print("Calculando percentiles de precipitación para cada evento usando procesamiento paralelo...")

def calcular_percentil_dia(args):
    fila, col_lat, col_lon = args
    archivo_nc_total = '/home/federico/Rect_Cuenca_p05/Rectangulo_Cuenca_en_p05_TOTAL.nc'
    try:
        fecha = fila['Fecha']
        lat = fila[col_lat]
        lon = fila[col_lon]
        valor_puntual = fila['Precip_Acum_Dia']
        if pd.isnull(fecha) or pd.isnull(lat) or pd.isnull(lon) or np.isnan(valor_puntual):
            return np.nan
        if isinstance(fecha, str):
            fecha = datetime.strptime(fecha, "%Y-%m-%d").date()
        mes = fecha.month
        valores_vector = []
        for anio in range(2011, 2024):
            ndays = calendar.monthrange(anio, mes)[1]
            for dia in range(1, ndays + 1):
                fecha_actual = datetime(anio, mes, dia).date()
                fecha_str = fecha_actual.strftime('%Y-%m-%d')
                comando = (
                    f"cdo output -fldmean -selcircle,lon={lon},lat={lat},radius=10km "
                    f"-seldate,{fecha_str} {archivo_nc_total}"
                )
                try:
                    resultado = subprocess.check_output(comando, shell=True).decode('utf-8').strip()
                    precip = float(resultado) if resultado != '' else np.nan
                except:
                    precip = np.nan
                valores_vector.append(precip)
        valores_vector = np.array(valores_vector)
        valores_vector = valores_vector[~np.isnan(valores_vector)]
        if len(valores_vector) > 0 and not np.isnan(valor_puntual):
            percentil = stats.percentileofscore(valores_vector, valor_puntual, kind="rank")
            return percentil
        else:
            return np.nan
    except Exception:
        return np.nan

###
def construir_vector_2dias_mes(lat, lon, mes_evento, archivo_nc_total):
    import calendar
    from datetime import datetime, timedelta
    import subprocess
    import numpy as np

    vector_2dias = []
    for anio in range(2011, 2024):
        ndays_mes = calendar.monthrange(anio, mes_evento)[1]
        # Definir el mes anterior y siguiente (para ajustar días extra)
        mes_anterior = mes_evento - 1 if mes_evento > 1 else 12
        anio_anterior = anio if mes_evento > 1 else anio - 1
        ndays_mes_anterior = calendar.monthrange(anio_anterior, mes_anterior)[1]
        mes_siguiente = mes_evento + 1 if mes_evento < 12 else 1
        anio_siguiente = anio if mes_evento < 12 else anio + 1

        # Generar 15 pares de días consecutivos para el mes de 30 días
        for i in range(15):
            dia1 = 2 * i + 1
            dia2 = dia1 + 1
            # Calcular fecha para dia1
            if dia1 <= ndays_mes:
                fecha1 = datetime(anio, mes_evento, dia1)
            else:
                fecha1 = datetime(anio_siguiente, mes_siguiente, dia1 - ndays_mes)
            # Calcular fecha para dia2
            if dia2 <= ndays_mes:
                fecha2 = datetime(anio, mes_evento, dia2)
            else:
                fecha2 = datetime(anio_siguiente, mes_siguiente, dia2 - ndays_mes)

            # Comando CDO para la suma de los dos días consecutivos
            comando = (
                f"cdo output -timsum -fldmean -selcircle,lon={lon},lat={lat},radius=10km "
                f"-seldate,{fecha1.strftime('%Y-%m-%d')},{fecha2.strftime('%Y-%m-%d')} {archivo_nc_total}"
            )
            try:
                resultado = subprocess.check_output(comando, shell=True).decode('utf-8').strip()
                valor = float(resultado) if resultado != '' else np.nan
            except:
                valor = np.nan
            vector_2dias.append(valor)
    # Filtrar NaN
    vector_2dias = [v for v in vector_2dias if not np.isnan(v)]
    return np.array(vector_2dias)

def calcular_percentil_2dias(args):
    from scipy import stats
    import pandas as pd
    import numpy as np
    from datetime import datetime

    fila, col_lat, col_lon = args
    archivo_nc_total = '/home/federico/Rect_Cuenca_p05/Rectangulo_Cuenca_en_p05_TOTAL.nc'
    try:
        lat = fila[col_lat]
        lon = fila[col_lon]
        valor_2dias = fila['Precip_Acum_2Dia'] if 'Precip_Acum_2Dia' in fila else fila['precip_2dias']
        fecha_evento = fila['Fecha']
        if pd.isnull(lat) or pd.isnull(lon) or np.isnan(valor_2dias) or pd.isnull(fecha_evento):
            return np.nan
        # Obtener mes del evento
        if isinstance(fecha_evento, str):
            fecha_evento = datetime.strptime(fecha_evento, "%Y-%m-%d").date()
        mes_evento = fecha_evento.month

        # Construir vector robusto de 15 pares x 13 años
        vector_2dias = construir_vector_2dias_mes(lat, lon, mes_evento, archivo_nc_total)
        if len(vector_2dias) > 0 and not np.isnan(valor_2dias):
            percentil = stats.percentileofscore(vector_2dias, valor_2dias, kind='rank')
            return percentil
        else:
            return np.nan
    except Exception as e:
        return np.nan

###

def calcular_percentil_week(args):
    fila, col_lat, col_lon = args
    archivo_nc_total = '/home/federico/Rect_Cuenca_p05/Rectangulo_Cuenca_en_p05_TOTAL.nc'
    try:
        fecha_evento = fila['Fecha']
        lat = fila[col_lat]
        lon = fila[col_lon]
        valor_semanal = fila['Precip_Acum_week']
        if pd.isnull(fecha_evento) or pd.isnull(lat) or pd.isnull(lon) or np.isnan(valor_semanal):
            return np.nan
        if isinstance(fecha_evento, str):
            fecha_evento = datetime.strptime(fecha_evento, "%Y-%m-%d").date()
        mes = fecha_evento.month
        vector_semanal = []
        for anio in range(2011, 2024):
            ndays = calendar.monthrange(anio, mes)[1]
            primer_dia_mes = datetime(anio, mes, 1).date()
            ultimo_dia_mes = datetime(anio, mes, ndays).date()
            dia_semana_inicio = primer_dia_mes.weekday()
            primer_dia_semana = primer_dia_mes - timedelta(days=dia_semana_inicio)
            current_ini = primer_dia_semana
            while True:
                current_fin = current_ini + timedelta(days=6)
                if current_ini > ultimo_dia_mes:
                    break
                if current_fin < primer_dia_mes:
                    current_ini += timedelta(days=7)
                    continue
                comando = (
                    f"cdo output -timsum -fldmean -selcircle,lon={lon},lat={lat},radius=10km "
                    f"-seldate,{current_ini.strftime('%Y-%m-%d')},{current_fin.strftime('%Y-%m-%d')} {archivo_nc_total}"
                )
                try:
                    resultado = subprocess.check_output(comando, shell=True).decode('utf-8').strip()
                    precip = float(resultado) if resultado != '' else np.nan
                except:
                    precip = np.nan
                vector_semanal.append(precip)
                current_ini += timedelta(days=7)
        vector_semanal = np.array(vector_semanal)
        vector_semanal = vector_semanal[~np.isnan(vector_semanal)]
        if len(vector_semanal) > 0 and not np.isnan(valor_semanal):
            percentil = stats.percentileofscore(vector_semanal, valor_semanal, kind='rank')
            return percentil
        else:
            return np.nan
    except Exception:
        return np.nan

def calcular_percentil_mes(args):
    fila, col_lat, col_lon = args
    archivo_nc_total = '/home/federico/Rect_Cuenca_p05/Rectangulo_Cuenca_en_p05_TOTAL.nc'
    try:
        fecha_evento = fila['Fecha']
        lat = fila[col_lat]
        lon = fila[col_lon]
        valor_mensual = fila['Precip_Acum_Mon']
        if pd.isnull(fecha_evento) or pd.isnull(lat) or pd.isnull(lon) or np.isnan(valor_mensual):
            return np.nan
        if isinstance(fecha_evento, str):
            fecha_evento = datetime.strptime(fecha_evento, "%Y-%m-%d").date()
        dia = fecha_evento.day
        mes = fecha_evento.month
        vector_mensual = []
        for anio in range(2011, 2024):
            fecha_fin1 = datetime(anio, mes, dia).date()
            fecha_ini1 = fecha_fin1 - timedelta(days=30)
            comando1 = (
                f"cdo output -timsum -fldmean -selcircle,lon={lon},lat={lat},radius=10km "
                f"-seldate,{fecha_ini1.strftime('%Y-%m-%d')},{fecha_fin1.strftime('%Y-%m-%d')} {archivo_nc_total}"
            )
            try:
                resultado1 = subprocess.check_output(comando1, shell=True).decode('utf-8').strip()
                precip1 = float(resultado1) if resultado1 != '' else np.nan
            except:
                precip1 = np.nan
            vector_mensual.append(precip1)

            fecha_ini2 = fecha_fin1 - timedelta(days=15)
            fecha_fin2 = fecha_fin1 + timedelta(days=14)
            comando2 = (
                f"cdo output -timsum -fldmean -selcircle,lon={lon},lat={lat},radius=10km "
                f"-seldate,{fecha_ini2.strftime('%Y-%m-%d')},{fecha_fin2.strftime('%Y-%m-%d')} {archivo_nc_total}"
            )
            try:
                resultado2 = subprocess.check_output(comando2, shell=True).decode('utf-8').strip()
                precip2 = float(resultado2) if resultado2 != '' else np.nan
            except:
                precip2 = np.nan
            vector_mensual.append(precip2)

            fecha_ini3 = fecha_fin1
            fecha_fin3 = fecha_ini3 + timedelta(days=30)
            comando3 = (
                f"cdo output -timsum -fldmean -selcircle,lon={lon},lat={lat},radius=10km "
                f"-seldate,{fecha_ini3.strftime('%Y-%m-%d')},{fecha_fin3.strftime('%Y-%m-%d')} {archivo_nc_total}"
            )
            try:
                resultado3 = subprocess.check_output(comando3, shell=True).decode('utf-8').strip()
                precip3 = float(resultado3) if resultado3 != '' else np.nan
            except:
                precip3 = np.nan
            vector_mensual.append(precip3)
        vector_mensual = np.array(vector_mensual)
        vector_mensual = vector_mensual[~np.isnan(vector_mensual)]
        if len(vector_mensual) > 0 and not np.isnan(valor_mensual):
            percentil = stats.percentileofscore(vector_mensual, valor_mensual, kind="rank")
            return percentil
        else:
            return np.nan
    except Exception:
        return np.nan

def calcular_percentil_tri_mes(args):
    fila, col_lat, col_lon = args
    archivo_nc_total = '/home/federico/Rect_Cuenca_p05/Rectangulo_Cuenca_en_p05_TOTAL.nc'
    try:
        fecha_evento = fila['Fecha']
        lat = fila[col_lat]
        lon = fila[col_lon]
        valor_trimestral = fila['Precip_Acum_3Mon']
        if pd.isnull(fecha_evento) or pd.isnull(lat) or pd.isnull(lon) or np.isnan(valor_trimestral):
            return np.nan
        if isinstance(fecha_evento, str):
            fecha_evento = datetime.strptime(fecha_evento, "%Y-%m-%d").date()
        dia = fecha_evento.day
        mes = fecha_evento.month
        vector_trimestral = []
        for anio in range(2011, 2024):
            fecha_fin1 = datetime(anio, mes, dia).date()
            fecha_ini1 = fecha_fin1 - timedelta(days=90)
            comando1 = (
                f"cdo output -timsum -fldmean -selcircle,lon={lon},lat={lat},radius=10km "
                f"-seldate,{fecha_ini1.strftime('%Y-%m-%d')},{fecha_fin1.strftime('%Y-%m-%d')} {archivo_nc_total}"
            )
            try:
                resultado1 = subprocess.check_output(comando1, shell=True).decode('utf-8').strip()
                precip1 = float(resultado1) if resultado1 != '' else np.nan
            except:
                precip1 = np.nan
            vector_trimestral.append(precip1)

            fecha_ini2 = fecha_fin1 - timedelta(days=45)
            fecha_fin2 = fecha_fin1 + timedelta(days=44)
            comando2 = (
                f"cdo output -timsum -fldmean -selcircle,lon={lon},lat={lat},radius=10km "
                f"-seldate,{fecha_ini2.strftime('%Y-%m-%d')},{fecha_fin2.strftime('%Y-%m-%d')} {archivo_nc_total}"
            )
            try:
                resultado2 = subprocess.check_output(comando2, shell=True).decode('utf-8').strip()
                precip2 = float(resultado2) if resultado2 != '' else np.nan
            except:
                precip2 = np.nan
            vector_trimestral.append(precip2)

            fecha_ini3 = fecha_fin1
            fecha_fin3 = fecha_ini3 + timedelta(days=90)
            comando3 = (
                f"cdo output -timsum -fldmean -selcircle,lon={lon},lat={lat},radius=10km "
                f"-seldate,{fecha_ini3.strftime('%Y-%m-%d')},{fecha_fin3.strftime('%Y-%m-%d')} {archivo_nc_total}"
            )
            try:
                resultado3 = subprocess.check_output(comando3, shell=True).decode('utf-8').strip()
                precip3 = float(resultado3) if resultado3 != '' else np.nan
            except:
                precip3 = np.nan
            vector_trimestral.append(precip3)
        vector_trimestral = np.array(vector_trimestral)
        vector_trimestral = vector_trimestral[~np.isnan(vector_trimestral)]
        if len(vector_trimestral) > 0 and not np.isnan(valor_trimestral):
            percentil = stats.percentileofscore(vector_trimestral, valor_trimestral, kind="rank")
            return percentil
        else:
            return np.nan
    except Exception:
        return np.nan


with ProcessPoolExecutor() as executor:
    args_list = [(fila, col_lat, col_lon) for _, fila in df_resultados.iterrows()]
    percentil_dia = list(executor.map(calcular_percentil_dia, args_list))
    percentil_2dias = list(executor.map(calcular_percentil_2dias, args_list))
    percentil_week = list(executor.map(calcular_percentil_week, args_list))
    percentil_mes = list(executor.map(calcular_percentil_mes, args_list))
    percentil_tri_mes = list(executor.map(calcular_percentil_tri_mes, args_list))

# Insertar columnas justo después de sus respectivas acumuladas
col_list = list(df_resultados.columns)
idx = col_list.index('Precip_Acum_Dia')
df_resultados.insert(idx + 1, 'Percentil_Dia', percentil_dia)

idx_2dias = df_resultados.columns.get_loc('Precip_Acum_2Dia')
df_resultados.insert(idx_2dias + 1, 'Percentil_2dias', percentil_2dias)

idx = df_resultados.columns.get_loc('Precip_Acum_week')
df_resultados.insert(idx + 1, 'Percentil_Week', percentil_week)

idx = df_resultados.columns.get_loc('Precip_Acum_Mon')
df_resultados.insert(idx + 1, 'Percentil_Mes', percentil_mes)

idx = df_resultados.columns.get_loc('Precip_Acum_3Mon')
df_resultados.insert(idx + 1, 'Percentil_Tri_Mes', percentil_tri_mes)

# --- INTEGRACIÓN HIDROGEOLÓGICA ---
print("Integrando información hidrogeológica...")

gdf_desliz = gpd.GeoDataFrame(
    df_resultados,
    geometry=[Point(xy) for xy in zip(df_resultados[col_lon], df_resultados[col_lat])],
    crs="EPSG:4326"
)

if hidrolito.crs != gdf_desliz.crs:
    hidrolito = hidrolito.to_crs(gdf_desliz.crs)

if 'Point' in list(hidrolito.geom_type.unique()):
    gdf_desliz_proj = gdf_desliz.to_crs(epsg=3857)
    gdf_hidro_proj = hidrolito.to_crs(epsg=3857)
    def obtener_atributos_hidro_proj(point, gdf_hidro_proj):
        dists = gdf_hidro_proj.distance(point)
        idx_min = dists.idxmin()
        return gdf_hidro_proj.loc[idx_min, ['Grupo_hidr', 'Litologia', 'Edad']]
    atributos_hidro = gdf_desliz_proj['geometry'].apply(lambda p: obtener_atributos_hidro_proj(p, gdf_hidro_proj))
    atributos_hidro = pd.DataFrame(list(atributos_hidro.values), index=gdf_desliz_proj.index)
else:
    join_result = gpd.sjoin(gdf_desliz, hidrolito[['Grupo_hidr', 'Litologia', 'Edad', 'geometry']],
                            how='left', predicate='intersects')
    atributos_hidro = join_result[['Grupo_hidr', 'Litologia', 'Edad']].reset_index(drop=True)

df_resultados = pd.concat([df_resultados.reset_index(drop=True), atributos_hidro.reset_index(drop=True)], axis=1)

# --- Reclasificación de 'Grupo_hidr' y cambio de nombre a 'litologia' ---
mapa_grupo_hidr = {
    'FV': 'RIv',
    'V': 'RIp',
    'PM-f': 'RIp',
    'PM': 'RM',
    'PM-n': 'RM',
    'S-Cz': 'RSc',
    'SC-Cz': 'RSq',
    'SC': 'RSm',
    'S': 'RSc',
    'VS': 'RSc',
    'NC': 'SNC'
}
df_resultados['Grupo_hidr'] = df_resultados['Grupo_hidr'].replace(mapa_grupo_hidr)
df_resultados = df_resultados.rename(columns={'Grupo_hidr': 'Grupo_hidrolito'})

# --- Reclasificación columna Grupo_hidrolito ---
mapeo_litologia_grupo = {
    'Gabros bandeados isotrópicos y dioritas': 'RIp',
    'Tobas, aglomerados y lavas': 'RIv',
    'Basaltos y andesitas basálticas': 'RIv',
    'Basaltos y andesitas intercalados con arenitas lodosas líticas, lodolitas carbonosas, arenitas feldespáticas con arenitas lodosas líticas, lodolitas carbonosas, arenitas feldespáticas, calizas y limolitas silíceas.':'RSm'
    # ... (agrega todas las litologías que necesites mapear)
}


# --- Extraer dato de pendiente del TIF ---

# Supón que tus columnas son 'lon' y 'lat'
gdf = gpd.GeoDataFrame(
    df_resultados, 
    geometry=gpd.points_from_xy(df_resultados[col_lon], df_resultados[col_lat]),
    crs='EPSG:4326'
)

# Cambia por el CRS del raster (usa el WKT si hace falta)
gdf = gdf.to_crs('ESRI:103599')

coords = [(geom.x, geom.y) for geom in gdf.geometry]

with rasterio.open('Raster_Pendientes.tif') as src:
    pendientes = [val[0] if (val is not None and val[0] != -9999) else np.nan for val in src.sample(coords)]

df_resultados['Pendiente_Grados'] = pendientes

# Pendiente en %
df_resultados['Pendiente_%'] = np.tan(np.radians(df_resultados['Pendiente_Grados'])) * 100


# --- Selección de columnas y guardado final ---
columnas_finales = [
    'Fecha', col_lat, col_lon, 'Tipo', 'Detonante', 'Departament', 'Incertidumb', 'Fallecidos',
    'TEMP_MIN', 'DURATION_H', 'AREA_KM2', 'Distancia_km', '# E_Convectivos', 'ID_Con',
    'Precip_Acum_Dia', 'Percentil_Dia', 'Precip_Acum_2Dia', 'Percentil_2dias', 'Precip_Acum_week', 'Percentil_Week',
    'Precip_Acum_Mon', 'Percentil_Mes', 'Precip_Acum_3Mon', 'Percentil_Tri_Mes',
    'Grupo_hidrolito', 'Litologia', 'Edad', 'Pendiente_%', 'Percentil_TEMP_MIN', 'Percentil_DURATION_H', 'Percentil_AREA_KM2'
]
salida = f"Resultado_Base_de_datos_desde_{fecha_ini}_a_{fecha_fin}_con_{N_dias_previos}_días_previos_para_asociar_eventos_convectivos_y_con_{umbral_km}_km_de_umbral_y_extras.csv"
df_resultados[columnas_finales].to_csv(salida, index=False)
print(f"Resultados guardados en {salida}")

print("=== CSV Final ===")
print(df_resultados[columnas_finales].to_string(index=False))

# === BLOQUE PARA MEDICIÓN Y REPORTE DE TIEMPOS ===
end_time = time.time()
total_time_sec = end_time - start_time
total_time_min = total_time_sec / 60
num_eventos = len(df_resultados)

print("\n========== RESUMEN DE EJECUCIÓN ==========")
print(f"Tiempo total de ejecución: {total_time_min:.2f} minutos ({total_time_sec:.2f} segundos)")
print(f"Número de eventos procesados: {num_eventos}")
if total_time_min > 0:
    print(f"Eventos procesados por minuto: {num_eventos / total_time_min:.2f}")
else:
    print("Demasiado rápido para calcular eventos por minuto.")

print("\n=============== CODIGO TERMINADO =============")



