import os
import uuid
from fastapi import FastAPI, HTTPException, Body, UploadFile, File
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from database import obtener_conexion
from datetime import datetime
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# ----------------- CONFIGURACIÓN DE ARCHIVOS -----------------
# Vercel Serverless requiere el uso de /tmp para archivos temporales de escritura
CARPETA_UPLOADS = "/tmp"
os.makedirs(CARPETA_UPLOADS, exist_ok=True)

# ----------------- PANEL DE ADMINISTRACIÓN DE BASE DE DATOS -----------------
# 1. Endpoint para ejecutar SQL directo desde la web
@app.post("/admin/ejecutar-sql")
def ejecutar_sql(datos: dict = Body(...)):
    query = datos.get("query", "").strip()
    if not query:
        raise HTTPException(status_code=400, detail="La consulta SQL no puede estar vacía")
    conexion = obtener_conexion()
    cursor = conexion.cursor(dictionary=True)
    try:
        cursor.execute(query)
        if query.upper().startswith("SELECT") or query.upper().startswith("SHOW"):
            resultados = cursor.fetchall()
            return {"tipo": "SELECT", "data": resultados}
        else:
            conexion.commit()
            return {"tipo": "COMANDO", "filas_afectadas": cursor.rowcount, "mensaje": "Consulta ejecutada correctamente"}
    except Exception as err:
        conexion.rollback()
        raise HTTPException(status_code=400, detail=f"Error en SQL: {str(err)}")
    finally:
        cursor.close()
        conexion.close()

# 2. Endpoint para obtener todos los registros de cualquier tabla
@app.get("/admin/tabla/{nombre_tabla}")
def obtener_tabla(nombre_tabla: str):
    tablas_permitidas = ["Usuarios", "Equipos", "Ordenes", "Areas", "Vehiculos"]
    if nombre_tabla not in tablas_permitidas:
        raise HTTPException(status_code=400, detail="Tabla no permitida")
    
    conexion = obtener_conexion()
    cursor = conexion.cursor(dictionary=True)
    try:
        if nombre_tabla == "Ordenes":
            query = """
                SELECT 
                    o.Id_Orden, 
                    o.Asunto, 
                    o.Descripcion, 
                    o.Fecha, 
                    o.Estatus, 
                    o.Prioridad, 
                    o.Id_Usuario_R, 
                    o.Id_Usuario_D
                FROM Ordenes o
                ORDER BY o.Id_Orden DESC
            """
            cursor.execute(query)
        else:
            cursor.execute(f"SELECT * FROM {nombre_tabla}")
            
        registros = cursor.fetchall()
        return {"tabla": nombre_tabla, "datos": registros}
    except Exception as err:
        raise HTTPException(status_code=400, detail=str(err))
    finally:
        cursor.close()
        conexion.close()

# 3. Función auxiliar para detectar la llave primaria de una tabla
def obtener_llave_primaria(cursor, nombre_tabla: str):
    cursor.execute(f"DESCRIBE {nombre_tabla}")
    columnas = cursor.fetchall()
    for col in columnas:
        if col["Key"] == "PRI":
            return col["Field"]
    return None

# 4. Endpoint para insertar un nuevo registro en cualquier tabla permitida
@app.post("/admin/tabla/{nombre_tabla}/insertar")
def insertar_registro(nombre_tabla: str, datos: dict = Body(...)):
    tablas_permitidas = ["Usuarios", "Equipos", "Ordenes", "Areas", "Vehiculos"]
    if nombre_tabla not in tablas_permitidas:
        raise HTTPException(status_code=400, detail="Tabla no permitida")
    conexion = obtener_conexion()
    cursor = conexion.cursor(dictionary=True)
    try:
        columnas = list(datos.keys())
        valores = list(datos.values())
        placeholders = ", ".join(["%s"] * len(valores))
        columnas_sql = ", ".join(columnas)
        query = f"INSERT INTO {nombre_tabla} ({columnas_sql}) VALUES ({placeholders})"
        cursor.execute(query, valores)
        conexion.commit()
        return {"mensaje": "Registro agregado correctamente", "id": cursor.lastrowid}
    except Exception as err:
        conexion.rollback()
        raise HTTPException(status_code=400, detail=f"Error al insertar: {str(err)}")
    finally:
        cursor.close()
        conexion.close()

# 5. Endpoint para actualizar un registro existente por su llave primaria
@app.put("/admin/tabla/{nombre_tabla}/actualizar/{valor_pk}")
def actualizar_registro(nombre_tabla: str, valor_pk: str, datos: dict = Body(...)):
    tablas_permitidas = ["Usuarios", "Equipos", "Ordenes", "Areas", "Vehiculos"]
    if nombre_tabla not in tablas_permitidas:
        raise HTTPException(status_code=400, detail="Tabla no permitida")
    conexion = obtener_conexion()
    cursor = conexion.cursor(dictionary=True)
    try:
        llave_pk = obtener_llave_primaria(cursor, nombre_tabla)
        if not llave_pk:
            raise HTTPException(status_code=400, detail="No se encontró llave primaria en la tabla")
        datos_filtrados = {k: v for k, v in datos.items() if k != llave_pk}
        set_clause = ", ".join([f"{col} = %s" for col in datos_filtrados.keys()])
        valores = list(datos_filtrados.values())
        valores.append(valor_pk)
        query = f"UPDATE {nombre_tabla} SET {set_clause} WHERE {llave_pk} = %s"
        cursor.execute(query, valores)
        conexion.commit()
        return {"mensaje": "Registro actualizado correctamente", "filas_afectadas": cursor.rowcount}
    except HTTPException:
        conexion.rollback()
        raise
    except Exception as err:
        conexion.rollback()
        raise HTTPException(status_code=400, detail=f"Error al actualizar: {str(err)}")
    finally:
        cursor.close()
        conexion.close()

# 6. Endpoint para eliminar un registro por su llave primaria
@app.delete("/admin/tabla/{nombre_tabla}/eliminar/{valor_pk}")
def eliminar_registro(nombre_tabla: str, valor_pk: str):
    tablas_permitidas = ["Usuarios", "Equipos", "Ordenes", "Areas", "Vehiculos"]
    if nombre_tabla not in tablas_permitidas:
        raise HTTPException(status_code=400, detail="Tabla no permitida")
    conexion = obtener_conexion()
    cursor = conexion.cursor(dictionary=True)
    try:
        llave_pk = obtener_llave_primaria(cursor, nombre_tabla)
        if not llave_pk:
            raise HTTPException(status_code=400, detail="No se encontró llave primaria en la tabla")
        query = f"DELETE FROM {nombre_tabla} WHERE {llave_pk} = %s"
        cursor.execute(query, (valor_pk,))
        conexion.commit()
        return {"mensaje": "Registro eliminado correctamente", "filas_afectadas": cursor.rowcount}
    except HTTPException:
        conexion.rollback()
        raise
    except Exception as err:
        conexion.rollback()
        raise HTTPException(status_code=400, detail=f"Error al eliminar: {str(err)}")
    finally:
        cursor.close()
        conexion.close()

# ----------------- MODELOS DE PYDANTIC -----------------
class LoginData(BaseModel):
    usuario: str
    password: str

class OrdenData(BaseModel):
    de_correo: str
    para_correo: str
    asunto: str
    descripcion: str
    fecha: str
    estatus: str
    prioridad: str
    id_usuario: int

class QueryData(BaseModel):
    query: str

class ReporteAyudaData(BaseModel):
    remitente: str
    nombre: str
    mensaje: str
    adjuntos: list[dict] = []

# ----------------- FUNCIÓN INTERNA DE CORREO -----------------
def enviar_email_notificacion(remitente_original: str, destinatario: str, asunto_orden: str, descripcion_orden: str, prioridad: str):
    correo_sistema = "tu_correo_sistema@gmail.com"
    password_sistema = "abcd efgh ijkl mnop"
    if correo_sistema == "tu_correo_sistema@gmail.com" or password_sistema == "abcd efgh ijkl mnop":
        print("⚠️ Correo del sistema no configurado todavía. Se omite el envío de notificación.")
        return False
    msg = MIMEMultipart()
    msg['From'] = correo_sistema
    msg['To'] = destinatario
    msg['Subject'] = f"[{prioridad.upper()}] Nueva Orden: {asunto_orden}"
    cuerpo_html = f"""
    <html>
        <body style="font-family: Arial, sans-serif; line-height: 1.6; color: #333;">
            <div style="max-width: 600px; margin: 0 auto; border: 1px solid #ddd; border-radius: 8px; overflow: hidden;">
                <div style="background-color: #0000FF; color: white; padding: 20px; text-align: center;">
                    <h2 style="margin: 0;">Nueva Orden de Trabajo Registrada</h2>
                </div>
                <div style="padding: 20px;">
                    <p>Hola, se ha generado una nueva orden asignada a tu cuenta:</p>
                    <table style="width: 100%; border-collapse: collapse;">
                        <tr>
                            <td style="padding: 8px 0; font-weight: bold; width: 30%;">Generada por:</td>
                            <td style="padding: 8px 0;">{remitente_original}</td>
                        </tr>
                        <tr>
                            <td style="padding: 8px 0; font-weight: bold;">Prioridad:</td>
                            <td style="padding: 8px 0;"><span style="background-color: #ffcccc; color: #cc0000; padding: 2px 8px; border-radius: 4px; font-size: 14px;">{prioridad}</span></td>
                        </tr>
                        <tr>
                            <td style="padding: 8px 0; font-weight: bold;">Asunto:</td>
                            <td style="padding: 8px 0;">{asunto_orden}</td>
                        </tr>
                    </table>
                    <br>
                    <div style="background-color: #f9f9f9; padding: 15px; border-left: 4px solid #0000FF; border-radius: 4px;">
                        <strong style="display: block; margin-bottom: 5px;">Descripción del requerimiento:</strong>
                        <p style="margin: 0; white-space: pre-wrap;">{descripcion_orden}</p>
                    </div>
                </div>
                <div style="background-color: #f1f1f1; padding: 10px; text-align: center; font-size: 12px; color: #666;">
                    Este es un mensaje automático del Sistema de Gestión de TI. Por favor no respondas a este correo.
                </div>
            </div>
        </body>
    </html>
    """
    msg.attach(MIMEText(cuerpo_html, 'html'))
    try:
        server = smtplib.SMTP('smtp.gmail.com', 587, timeout=10)
        server.starttls()
        server.login(correo_sistema, password_sistema)
        server.sendmail(correo_sistema, destinatario, msg.as_string())
        server.quit()
        return True
    except Exception as e:
        print(f"Error crítico al enviar el correo: {e}")
        return False

def enviar_email_reporte_ayuda(remitente: str, nombre: str, mensaje: str, adjuntos: list[dict]):
    correo_sistema = "tu_correo_sistema@gmail.com"
    password_sistema = "abcd efgh ijkl mnop"
    destinatario_ti = "jesus,zc@soluciones-sharl.com"
    if correo_sistema == "tu_correo_sistema@gmail.com" or password_sistema == "abcd efgh ijkl mnop":
        print("⚠️ Correo del sistema no configurado todavía. Se omite el envío del reporte de ayuda.")
        return False

    msg = MIMEMultipart()
    msg['From'] = correo_sistema
    msg['To'] = destinatario_ti
    msg['Subject'] = f"[REPORTE DE AYUDA] {remitente}"

    lista_adjuntos_html = ""
    if adjuntos:
        lista_adjuntos_html = "<ul>"
        for archivo in adjuntos:
            nombre_archivo = archivo.get('nombre', 'adjunto')
            url_archivo = archivo.get('url', '#')
            lista_adjuntos_html += f"<li><a href='{url_archivo}' target='_blank' rel='noopener noreferrer'>{nombre_archivo}</a></li>"
        lista_adjuntos_html += "</ul>"

    cuerpo_html = f"""
    <html>
        <body style="font-family: Arial, sans-serif; line-height: 1.6; color: #333;">
            <div style="max-width: 600px; margin: 0 auto; border: 1px solid #ddd; border-radius: 8px; overflow: hidden;">
                <div style="background-color: #0000FF; color: white; padding: 20px; text-align: center;">
                    <h2 style="margin: 0;">Nuevo Reporte de Ayuda</h2>
                </div>
                <div style="padding: 20px;">
                    <p>Se ha recibido un nuevo reporte desde la plataforma.</p>
                    <table style="width: 100%; border-collapse: collapse;">
                        <tr>
                            <td style="padding: 8px 0; font-weight: bold; width: 30%;">Remitente:</td>
                            <td style="padding: 8px 0;">{remitente}</td>
                        </tr>
                        <tr>
                            <td style="padding: 8px 0; font-weight: bold;">Nombre:</td>
                            <td style="padding: 8px 0;">{nombre}</td>
                        </tr>
                    </table>
                    <br>
                    <div style="background-color: #f9f9f9; padding: 15px; border-left: 4px solid #0000FF; border-radius: 4px;">
                        <strong style="display: block; margin-bottom: 5px;">Mensaje:</strong>
                        <p style="margin: 0; white-space: pre-wrap;">{mensaje}</p>
                    </div>
                    {('<div style="margin-top: 20px;"><strong>Archivos adjuntos:</strong>' + lista_adjuntos_html + '</div>') if adjuntos else ''}
                </div>
                <div style="background-color: #f1f1f1; padding: 10px; text-align: center; font-size: 12px; color: #666;">
                    Este es un mensaje automático del Centro de Ayuda. No responder a este correo.
                </div>
            </div>
        </body>
    </html>
    """
    msg.attach(MIMEText(cuerpo_html, 'html'))
    try:
        server = smtplib.SMTP('smtp.gmail.com', 587, timeout=10)
        server.starttls()
        server.login(correo_sistema, password_sistema)
        server.sendmail(correo_sistema, destinatario_ti, msg.as_string())
        server.quit()
        return True
    except Exception as e:
        print(f"Error crítico al enviar el correo de ayuda: {e}")
        return False

# ----------------- ENDPOINTS DE LA API -----------------
@app.get("/")
def home():
    return {"mensaje": "API funcionando correctamente"}

@app.post("/login")
def login(data: LoginData):
    conexion = obtener_conexion()
    cursor = conexion.cursor(dictionary=True)
    try:
        cursor.execute(
            "SELECT Id_Usuario, Nombres, Contraseña, Rol FROM Usuarios WHERE Correo = %s",
            (data.usuario,)
        )
        usuario_db = cursor.fetchone()
    except Exception as err:
        raise HTTPException(status_code=500, detail=f"Error de base de datos en login: {str(err)}")
    finally:
        cursor.close()
        conexion.close()
    if not usuario_db:
        raise HTTPException(status_code=401, detail="Usuario no encontrado")
    if usuario_db["Contraseña"] != data.password:
        raise HTTPException(status_code=401, detail="Contraseña incorrecta")
    rol_normalizado = usuario_db["Rol"].lower()
    return {
        "id": usuario_db["Id_Usuario"],
        "nombre": usuario_db["Nombres"],
        "rol": rol_normalizado
    }

@app.get("/usuarios/{id_usuario}/perfil")
def obtener_perfil(id_usuario: int):
    conexion = obtener_conexion()
    cursor = conexion.cursor(dictionary=True)
    cursor.execute(
        """
        SELECT 
            u.Id_Usuario, u.Nombres, u.Apellidos, u.Correo, u.Telefono, u.Puesto, u.Rol, u.Ciudad, u.Oficina, 
            a.Nombre_Area,
            e.Id_Equipo, e.Marca, e.Tipo, e.Sistema_Operativo, e.RAM, e.ROM, e.Estatus,
            v.Placa, v.Marca AS Marca_Vehiculo, v.Modelo AS Modelo_Vehiculo, v.Año AS Anio_Vehiculo, v.Color AS Color_Vehiculo
        FROM Usuarios u
        LEFT JOIN Areas a ON a.Id_Area = u.Id_Area1
        LEFT JOIN Equipos e ON e.id_Usuario1 = u.Id_Usuario
        LEFT JOIN Vehiculos v ON v.Id_Responsable = u.Id_Usuario
        WHERE u.Id_Usuario = %s
        """,
        (id_usuario,)
    )
    resultado = cursor.fetchone()
    cursor.close()
    conexion.close()
    if not resultado:
        raise HTTPException(status_code=404, detail="Usuario no encontrado")
    return resultado

@app.post("/ordenes")
def crear_orden(data: OrdenData):
    conexion = obtener_conexion()
    cursor = conexion.cursor()
    try:
        fecha_limpia = data.fecha.replace('Z', '')
        fecha_convertida = datetime.strptime(fecha_limpia, "%Y-%m-%dT%H:%M:%S.%f")
    except:
        try:
            fecha_convertida = datetime.strptime(fecha_limpia, "%Y-%m-%dT%H:%M:%S")
        except:
            fecha_convertida = datetime.now()
    try:
        cursor_lookup = conexion.cursor(dictionary=True)
        cursor_lookup.execute("SELECT Id_Usuario FROM Usuarios WHERE Correo = %s", (data.de_correo,))
        usuario_envia = cursor_lookup.fetchone()
        cursor_lookup.execute("SELECT Id_Usuario FROM Usuarios WHERE Correo = %s", (data.para_correo,))
        usuario_recibe = cursor_lookup.fetchone()
        cursor_lookup.close()
        if not usuario_envia or not usuario_recibe:
            raise HTTPException(status_code=400, detail="El correo remitente o destinatario no está registrado en Usuarios")
        id_usuario_envia = usuario_envia["Id_Usuario"]
        id_usuario_recibe = usuario_recibe["Id_Usuario"]
        cursor.execute(
            """INSERT INTO Ordenes (Asunto, Descripcion, Fecha, Id_Usuario_R, Id_Usuario_D, Estatus, Prioridad)
               VALUES (%s, %s, %s, %s, %s, %s, %s)""",
            (
                data.asunto,
                data.descripcion,
                fecha_convertida,
                id_usuario_envia,
                id_usuario_recibe,
                data.estatus,
                data.prioridad
            )
        )
        id_orden_nueva = cursor.lastrowid
        cursor.execute(
            """INSERT INTO Notificaciones 
               (Fecha, titulo, tipo, vista, mensaje, Id_Usuario_6, Estatus1, Prioridad1, id_Orden1)
               VALUES (NOW(), %s, %s, FALSE, %s, %s, %s, %s, %s)""",
            (
                "Nueva orden creada",
                "orden",
                f"Se ha registrado la orden: {data.asunto}",
                data.id_usuario,
                data.estatus,
                data.prioridad,
                id_orden_nueva
            )
        )
        conexion.commit()
    except HTTPException:
        conexion.rollback()
        cursor.close()
        conexion.close()
        raise
    except Exception as e:
        conexion.rollback()
        cursor.close()
        conexion.close()
        raise HTTPException(status_code=400, detail=f"Error al guardar la orden: {str(e)}")
    cursor.close()
    conexion.close()
    
    enviar_email_notificacion(
        remitente_original=data.de_correo,
        destinatario=data.para_correo,
        asunto_orden=data.asunto,
        descripcion_orden=data.descripcion,
        prioridad=data.prioridad
    )
    return {"mensaje": "Orden creada correctamente y correo enviado"}

@app.post("/ayuda/reportar")
def reportar_ayuda(data: ReporteAyudaData):
    enviado = enviar_email_reporte_ayuda(
        remitente=data.remitente,
        nombre=data.nombre,
        mensaje=data.mensaje,
        adjuntos=data.adjuntos
    )
    if not enviado:
        return {"mensaje": "Reporte recibido, pero el correo no se envió porque el sistema de correo no está configurado."}
    return {"mensaje": "Reporte enviado correctamente a soporte técnico."}

# ----------------- SUBIDA DE ARCHIVOS ADJUNTOS EN ÓRDENES -----------------
@app.post("/ordenes/subir-archivo")
async def subir_archivo(file: UploadFile = File(...)):
    extension = os.path.splitext(file.filename)[1]
    nombre_unico = f"{uuid.uuid4()}{extension}"
    ruta_completa = os.path.join(CARPETA_UPLOADS, nombre_unico)
    try:
        contenido = await file.read()
        with open(ruta_completa, "wb") as f:
            f.write(contenido)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error al guardar el archivo: {str(e)}")
    
    url_publica = f"/uploads/{nombre_unico}"
    return {
        "nombre_original": file.filename,
        "url": url_publica
    }

# ----------------- VISTAS DE ADMINISTRACIÓN -----------------
@app.get("/admin/areas")
def get_areas():
    conexion = obtener_conexion()
    cursor = conexion.cursor(dictionary=True)
    cursor.execute("SELECT * FROM Areas")
    resultado = cursor.fetchall()
    cursor.close()
    conexion.close()
    return resultado

@app.get("/admin/usuarios")
def get_usuarios():
    conexion = obtener_conexion()
    cursor = conexion.cursor(dictionary=True)
    cursor.execute("SELECT Id_Usuario, Nombres, Apellidos, Correo, Telefono, Puesto, Rol, Ciudad, Oficina, Id_Area1 FROM Usuarios")
    resultado = cursor.fetchall()
    cursor.close()
    conexion.close()
    return resultado

@app.get("/admin/equipos")
def get_equipos():
    conexion = obtener_conexion()
    cursor = conexion.cursor(dictionary=True)
    cursor.execute("SELECT * FROM Equipos")
    resultado = cursor.fetchall()
    cursor.close()
    conexion.close()
    return resultado

@app.get("/admin/ordenes")
def get_ordenes():
    conexion = obtener_conexion()
    cursor = conexion.cursor(dictionary=True)
    cursor.execute("SELECT * FROM Ordenes")
    resultado = cursor.fetchall()
    cursor.close()
    conexion.close()
    return resultado

@app.get("/admin/vehiculos")
def get_vehiculos():
    conexion = obtener_conexion()
    cursor = conexion.cursor(dictionary=True)
    cursor.execute("SELECT * FROM Vehiculos")
    resultado = cursor.fetchall()
    cursor.close()
    conexion.close()
    return resultado

@app.get("/admin/stats")
def get_stats():
    conexion = obtener_conexion()
    cursor = conexion.cursor(dictionary=True)
    cursor.execute("SELECT COUNT(*) as total FROM Usuarios")
    usuarios = cursor.fetchone()["total"]
    cursor.execute("SELECT COUNT(*) as total FROM Equipos")
    equipos = cursor.fetchone()["total"]
    cursor.execute("SELECT COUNT(*) as total FROM Ordenes WHERE Estatus='Pendiente'")
    ordenes = cursor.fetchone()["total"]
    cursor.execute("SELECT COUNT(*) as total FROM Areas")
    areas = cursor.fetchone()["total"]
    cursor.close()
    conexion.close()
    return {"usuarios": usuarios, "equipos": equipos, "ordenes_pendientes": ordenes, "areas": areas}

@app.get("/stats")
def get_stats_alias():
    return get_stats()

@app.post("/admin/query")
def ejecutar_query(data: QueryData):
    conexion = obtener_conexion()
    cursor = conexion.cursor(dictionary=True)
    try:
        cursor.execute(data.query)
        q = data.query.strip().upper()
        if q.startswith("SELECT") or q.startswith("SHOW") or q.startswith("DESCRIBE"):
            resultado = cursor.fetchall()
            return {"columnas": list(resultado[0].keys()) if resultado else [], "filas": resultado}
        else:
            conexion.commit()
            return {"mensaje": f"{cursor.rowcount} fila(s) afectada(s)"}
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))
    finally:
        cursor.close()
        conexion.close()

@app.get("/mis-ordenes")
def obtener_mis_ordenes(correo: str, estatus: str):
    conexion = obtener_conexion()
    cursor = conexion.cursor(dictionary=True)
    try:
        query = """
            SELECT o.*, u1.Correo as de_correo, u2.Correo as para_correo 
            FROM Ordenes o
            INNER JOIN Usuarios u1 ON o.Id_Usuario_R = u1.Id_Usuario
            INNER JOIN Usuarios u2 ON o.Id_Usuario_D = u2.Id_Usuario
            WHERE (u1.Correo = %s OR u2.Correo = %s) 
            AND o.Estatus = %s
            ORDER BY o.Fecha DESC
        """
        cursor.execute(query, (correo, correo, estatus))
        ordenes = cursor.fetchall()
        return ordenes if ordenes is not None else []
    except Exception as e:
        print(f"Error en /mis-ordenes: {e}")
        return []
    finally:
        cursor.close()
        conexion.close()

@app.get("/notificaciones/{id_usuario}")
def get_notificaciones(id_usuario: int):
    conexion = obtener_conexion()
    cursor = conexion.cursor(dictionary=True)
    cursor.execute(
        "SELECT * FROM Notificaciones WHERE Id_Usuario_6 = %s ORDER BY Fecha DESC",
        (id_usuario,)
    )
    resultado = cursor.fetchall()
    cursor.close()
    conexion.close()
    return resultado

@app.put("/notificaciones/{id_notificacion}/vista")
def marcar_vista(id_notificacion: int):
    conexion = obtener_conexion()
    cursor = conexion.cursor()
    cursor.execute(
        "UPDATE Notificaciones SET vista = TRUE WHERE id_Notificacion = %s",
        (id_notificacion,)
    )
    conexion.commit()
    cursor.close()
    conexion.close()
    return {"mensaje": "Notificación marcada como vista"}

@app.get("/notificaciones/{id_usuario}/conteo")
def contar_no_leidas(id_usuario: int):
    conexion = obtener_conexion()
    cursor = conexion.cursor(dictionary=True)
    cursor.execute(
        "SELECT COUNT(*) as total FROM Notificaciones WHERE Id_Usuario_6 = %s AND vista = FALSE",
        (id_usuario,)
    )
    total = cursor.fetchone()["total"]
    cursor.close()
    conexion.close()
    return {"no_leidas": total}