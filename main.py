from fastapi import FastAPI, HTTPException, Depends
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
from sqlalchemy import (
    create_engine,
    Column,
    Integer,
    Float,
    Boolean,
    DateTime,
    text,
)
from sqlalchemy.orm import declarative_base, Session, sessionmaker
from datetime import datetime, timezone
from typing import Optional


# ---------------------------------------------------------------------------
# 1. CONFIGURACIÓN DE BASE DE DATOS
# ---------------------------------------------------------------------------

DATABASE_URL = "sqlite:///./germinador.db"

# check_same_thread=False es necesario para SQLite con FastAPI (multi-thread)
engine = create_engine(
    DATABASE_URL,
    connect_args={"check_same_thread": False},
)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()


# ---------------------------------------------------------------------------
# 2. MODELO ORM (Tabla en SQLite)
# ---------------------------------------------------------------------------

class Telemetria(Base):
    """
    Tabla: telemetria
    Almacena cada lectura enviada por el ESP32.
    """
    __tablename__ = "telemetria"

    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    timestamp = Column(DateTime, nullable=False, default=lambda: datetime.now(timezone.utc))

    # Sensores ambientales
    temperatura      = Column(Float,   nullable=False)
    humedad_aire     = Column(Float,   nullable=False)
    humedad_suelo    = Column(Float,   nullable=False)
    humedad_suelo2    = Column(Float,   nullable=False)
    humedad_suelo3    = Column(Float,   nullable=False)
    humedad_suelo4    = Column(Float,   nullable=False)
    luz_lux          = Column(Integer, nullable=False)
    ph_simulado      = Column(Float,   nullable=False)

    # Actuadores / estados
    estado_bomba     = Column(Boolean, nullable=False)
    estado_ventilador = Column(Boolean, nullable=False)
    estado_ventilador2 = Column(Boolean, nullable=False)
    bombillo    = Column(Boolean, nullable=False)


# Crea el archivo .db y la tabla si no existen todavía
Base.metadata.create_all(bind=engine)


# ---------------------------------------------------------------------------
# 3. SCHEMAS PYDANTIC
# ---------------------------------------------------------------------------

class TelemetriaInput(BaseModel):
    """
    Payload que envía el ESP32 al endpoint POST /api/telemetria.
    No incluye 'id' ni 'timestamp': la DB los genera automáticamente.
    """
    temperatura:       float = Field(..., ge=-40.0, le=125.0,  description="°C")
    humedad_aire:      float = Field(..., ge=0.0,   le=100.0,  description="%  RH")
    humedad_suelo:     float = Field(..., ge=0.0,   le=100.0,  description="% capacitivo")
    humedad_suelo2:     float = Field(..., ge=0.0,   le=100.0,  description="% capacitivo")
    humedad_suelo3:     float = Field(..., ge=0.0,   le=100.0,  description="% capacitivo")
    humedad_suelo4:     float = Field(..., ge=0.0,   le=100.0,  description="% capacitivo")
    luz_lux:           int   = Field(..., ge=0,                description="lux")
    ph_simulado:       float = Field(..., ge=0.0,   le=14.0,   description="pH")
    estado_bomba:      bool  = Field(...,                      description="True = encendida")
    estado_ventilador: bool  = Field(...,                      description="True = encendido")
    estado_ventilador2: bool  = Field(...,                      description="True = encendido")
    bombillo:     bool  = Field(...,                      description="True = encendido")

    model_config = {
        "json_schema_extra": {
            "example": {
                "temperatura": 24.5,
                "humedad_aire": 68.3,
                "humedad_suelo": 45.0,
                "humedad_suelo2": 45.0,
                "humedad_suelo3": 45.0,
                "humedad_suelo4": 45.0,
                "luz_lux": 3200,
                "ph_simulado": 6.8,
                "estado_bomba": False,
                "estado_ventilador": True,
                "estado_ventilador2": False,
                "bombillo": False,
            }
        }
    }


class TelemetriaOutput(BaseModel):
    """
    Respuesta que consume la App Kotlin desde GET /api/estado.
    Incluye todos los campos, más id y timestamp.
    """
    id:                int
    timestamp:         datetime
    temperatura:       float
    humedad_aire:      float
    humedad_suelo:     float
    humedad_suelo2:     float
    humedad_suelo3:     float
    humedad_suelo4:     float
    luz_lux:           int
    ph_simulado:       float
    estado_bomba:      bool
    estado_ventilador: bool
    estado_ventilador2: bool
    bombillo:     bool

    model_config = {"from_attributes": True}


class PostResponse(BaseModel):
    mensaje: str
    id:      int


# ---------------------------------------------------------------------------
# 4. DEPENDENCIA DE SESIÓN
# ---------------------------------------------------------------------------

def get_db():
    """
    Generador que provee una sesión de DB por request
    y garantiza su cierre al finalizar.
    """
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


# ---------------------------------------------------------------------------
# 5. INSTANCIA FASTAPI + CORS
# ---------------------------------------------------------------------------

app = FastAPI(
    title="Germinador IoT API",
    description="Backend para recibir telemetría del ESP32 y servir estado a la App Kotlin.",
    version="1.0.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],      # Permitir cualquier origen (útil en desarrollo/pruebas)
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ---------------------------------------------------------------------------
# 6. ENDPOINTS
# ---------------------------------------------------------------------------

@app.post(
    "/api/telemetria",
    response_model=PostResponse,
    status_code=201,
    summary="Recibe telemetría del ESP32",
    tags=["IoT"],
)
def recibir_telemetria(
    payload: TelemetriaInput,
    db: Session = Depends(get_db),
):
    """
    **Productor:** ESP32  
    Guarda una nueva fila en la tabla `telemetria` con timestamp UTC automático.
    Devuelve el ID asignado para confirmación.
    """
    nuevo_registro = Telemetria(
        timestamp         = datetime.now(timezone.utc),
        temperatura       = payload.temperatura,
        humedad_aire      = payload.humedad_aire,
        humedad_suelo     = payload.humedad_suelo,
        humedad_suelo2     = payload.humedad_suelo2,
        humedad_suelo3     = payload.humedad_suelo3,
        humedad_suelo4     = payload.humedad_suelo4,
        luz_lux           = payload.luz_lux,
        ph_simulado       = payload.ph_simulado,
        estado_bomba      = payload.estado_bomba,
        estado_ventilador = payload.estado_ventilador,
        estado_ventilador2 = payload.estado_ventilador2,
        bombillo           = payload.bombillo,
    )

    db.add(nuevo_registro)
    db.commit()
    db.refresh(nuevo_registro)   # Carga el id autoincremental generado

    return PostResponse(
        mensaje=f"Registro guardado correctamente.",
        id=nuevo_registro.id,
    )


@app.get(
    "/api/estado",
    response_model=TelemetriaOutput,
    status_code=200,
    summary="Devuelve el último estado del germinador",
    tags=["App"],
)
def obtener_ultimo_estado(db: Session = Depends(get_db)):
    """
    **Consumidor:** App Kotlin  
    Retorna la fila más reciente de `telemetria` ordenando por `id` DESC.  
    Devuelve **404** si la tabla aún no tiene registros.
    """
    ultimo = (
        db.query(Telemetria)
        .order_by(Telemetria.id.desc())
        .first()
    )

    if ultimo is None:
        raise HTTPException(
            status_code=404,
            detail="No hay registros de telemetría en la base de datos.",
        )

    return ultimo


# ---------------------------------------------------------------------------
# 7. HEALTH CHECK (opcional pero recomendado en VPS)
# ---------------------------------------------------------------------------

@app.get("/health", tags=["Sistema"], summary="Verifica que la API esté activa")
def health_check():
    return {"status": "ok", "timestamp": datetime.now(timezone.utc).isoformat()}


# ---------------------------------------------------------------------------
# 8. PUNTO DE ENTRADA (desarrollo local)
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)