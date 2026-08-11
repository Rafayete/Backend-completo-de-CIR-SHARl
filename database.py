#database.py
import os
import mysql.connector

def obtener_conexion():
    return mysql.connector.connect(
        # Si existe la variable en Render la usa, si no, usa localhost
        host=os.getenv("DB_HOST", "localhost"),
        port=int(os.getenv("DB_PORT", 3306)),
        user=os.getenv("DB_USER", "root"),
        password=os.getenv("DB_PASSWORD", ""),  # Pon tu clave local si usas
        database=os.getenv("DB_NAME", "BD_CIR_sharl")
    )