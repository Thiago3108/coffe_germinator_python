import logging
import os
from datetime import datetime, timezone, timedelta
from typing import Literal, Optional

from dotenv import load_dotenv
from fastapi import Depends, FastAPI, Header, HTTPException, Path, Query
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field, model_validator
from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    Float,
    Index,
    Integer,
    String,
    create_engine,
)
from sqlalchemy.orm import Session, declarative_base, sessionmaker


# ---------------------------------------------------------------------------
# 0. CONFIG
# ---------------------------------------------------------------------------

load_dotenv()

DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./germinador.db")
API_TOKEN    = os.getenv("API_TOKEN", "").strip()
CORS_ORIGINS = [o.strip() for o in os.getenv("CORS_ORIGINS", "").split(",") if o.strip()]
PORT         = int(os.getenv("PORT", "8001"))

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
log = logging.getLogger("germinador")

if not API_TOKEN:
    log.warning(
        "API_TOKEN no está configurado en .env — los endpoints aceptarán "
        "cualquier request. NO uses esto en producción."
    )

ACTUADORES_VALIDOS = ("bomba", "ventilador", "luz")
ActuadorLit = Literal["bomba", "ventilador", "luz"]

TIPOS_ALERTA = ("tanque_vacio", "temp_alta", "sensor_offline", "bomba_prolongada")
TipoAlertaLit = Literal["tanque_vacio", "temp_alta", "sensor_offline", "bomba_prolongada"]

# Cuánto tiempo esperar antes de re-emitir una alerta del MISMO tipo no resuelta.
COOLDOWN_ALERTAS_MIN = 30

# Umbrales fijos de evaluación de alertas (independientes de los setpoints).
ALERTA_TEMP_ALTA_C        = 28.0  # T > esto en 3 lecturas seguidas
ALERTA_TEMP_ALTA_N        = 3
ALERTA_BOMBA_LECTURAS_ON  = 6     # 6 lecturas × 10s ≈ 60s de bomba prolongada


# ---------------------------------------------------------------------------
# 1. BASE DE DATOS
# ---------------------------------------------------------------------------

engine = create_engine(
    DATABASE_URL,
    connect_args={"check_same_thread": False} if DATABASE_URL.startswith("sqlite") else {},
)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()


class Telemetria(Base):
    __tablename__ = "telemetria"

    id        = Column(Integer, primary_key=True, index=True, autoincrement=True)
    timestamp = Column(DateTime, nullable=False, default=lambda: datetime.now(timezone.utc))

    temperatura       = Column(Float,   nullable=False)
    humedad_aire      = Column(Float,   nullable=False)
    humedad_suelo     = Column(Float,   nullable=False)
    humedad_suelo2    = Column(Float,   nullable=False)
    humedad_suelo3    = Column(Float,   nullable=False)
    humedad_suelo4    = Column(Float,   nullable=False)
    luz_lux           = Column(Integer, nullable=False)
    ph_simulado       = Column(Float,   nullable=False)

    estado_bomba       = Column(Boolean, nullable=False)
    estado_ventilador  = Column(Boolean, nullable=False)
    estado_ventilador2 = Column(Boolean, nullable=False)
    bombillo           = Column(Boolean, nullable=False)

    nivel_agua_cm   = Column(Float, nullable=False, default=0.0)
    nivel_agua_pct  = Column(Float, nullable=False, default=0.0)


Index("ix_telemetria_timestamp", Telemetria.timestamp)


class Setpoints(Base):
    __tablename__ = "setpoints"

    id              = Column(Integer, primary_key=True, autoincrement=False, default=1)
    temp_min        = Column(Float, nullable=False, default=20.0)
    temp_vent_on    = Column(Float, nullable=False, default=25.0)
    temp_vent_off   = Column(Float, nullable=False, default=23.5)
    suelo_bomba_on  = Column(Float, nullable=False, default=40.0)
    suelo_bomba_off = Column(Float, nullable=False, default=70.0)
    luz_on_lx       = Column(Float, nullable=False, default=150.0)
    luz_off_lx      = Column(Float, nullable=False, default=300.0)

    nivel_vacio_cm     = Column(Float, nullable=False, default=15.0)
    nivel_lleno_cm     = Column(Float, nullable=False, default=3.0)
    nivel_agua_min_pct = Column(Float, nullable=False, default=15.0)

    actualizado_en  = Column(DateTime, nullable=False, default=lambda: datetime.now(timezone.utc))


class Override(Base):
    __tablename__ = "overrides"

    actuador      = Column(String(20), primary_key=True)
    forzar_estado = Column(Boolean, nullable=False)
    expira_en     = Column(DateTime, nullable=False)
    creado_en     = Column(DateTime, nullable=False, default=lambda: datetime.now(timezone.utc))


class Alerta(Base):
    """
    Alertas generadas automáticamente al recibir telemetría.
    Cada alerta vive hasta que el usuario la marca como resuelta.
    """
    __tablename__ = "alertas"

    id         = Column(Integer, primary_key=True, autoincrement=True)
    timestamp  = Column(DateTime, nullable=False, default=lambda: datetime.now(timezone.utc))
    tipo       = Column(String(40), nullable=False, index=True)   # uno de TIPOS_ALERTA
    severidad  = Column(String(10), nullable=False, default="warn")  # info | warn | critical
    titulo     = Column(String(80), nullable=False)
    mensaje    = Column(String(400), nullable=False)
    resuelta   = Column(Boolean, nullable=False, default=False, index=True)
    resuelta_en = Column(DateTime, nullable=True)


Index("ix_alertas_tipo_resuelta", Alerta.tipo, Alerta.resuelta)


Base.metadata.create_all(bind=engine)


def _bootstrap_setpoints() -> None:
    db = SessionLocal()
    try:
        if db.query(Setpoints).first() is None:
            db.add(Setpoints(id=1))
            db.commit()
            log.info("Setpoints inicializados con valores por defecto.")
    finally:
        db.close()


_bootstrap_setpoints()


# ---------------------------------------------------------------------------
# 2. SCHEMAS
# ---------------------------------------------------------------------------

class TelemetriaInput(BaseModel):
    temperatura:        float = Field(..., ge=-40.0, le=125.0)
    humedad_aire:       float = Field(..., ge=0.0,   le=100.0)
    humedad_suelo:      float = Field(..., ge=0.0,   le=100.0)
    humedad_suelo2:     float = Field(..., ge=0.0,   le=100.0)
    humedad_suelo3:     float = Field(..., ge=0.0,   le=100.0)
    humedad_suelo4:     float = Field(..., ge=0.0,   le=100.0)
    luz_lux:            int   = Field(..., ge=0)
    ph_simulado:        float = Field(..., ge=0.0,   le=14.0)
    estado_bomba:       bool
    estado_ventilador:  bool
    estado_ventilador2: bool
    bombillo:           bool
    nivel_agua_cm:      Optional[float] = Field(default=0.0, ge=0.0, le=400.0)
    nivel_agua_pct:     Optional[float] = Field(default=0.0, ge=0.0, le=100.0)
    sensor_aht_ok:      Optional[bool]  = None
    sensor_luz_ok:      Optional[bool]  = None
    sensor_nivel_ok:    Optional[bool]  = None


class TelemetriaOutput(BaseModel):
    id:                 int
    timestamp:          datetime
    temperatura:        float
    humedad_aire:       float
    humedad_suelo:      float
    humedad_suelo2:     float
    humedad_suelo3:     float
    humedad_suelo4:     float
    luz_lux:            int
    ph_simulado:        float
    estado_bomba:       bool
    estado_ventilador:  bool
    estado_ventilador2: bool
    bombillo:           bool
    nivel_agua_cm:      float
    nivel_agua_pct:     float

    model_config = {"from_attributes": True}


class PostResponse(BaseModel):
    mensaje: str
    id:      int


class SetpointsBase(BaseModel):
    temp_min:        float = Field(..., ge=0.0,  le=40.0)
    temp_vent_on:    float = Field(..., ge=10.0, le=45.0)
    temp_vent_off:   float = Field(..., ge=10.0, le=45.0)
    suelo_bomba_on:  float = Field(..., ge=0.0,  le=100.0)
    suelo_bomba_off: float = Field(..., ge=0.0,  le=100.0)
    luz_on_lx:       float = Field(..., ge=0.0,  le=10000.0)
    luz_off_lx:      float = Field(..., ge=0.0,  le=10000.0)
    nivel_vacio_cm:     float = Field(..., ge=1.0, le=200.0)
    nivel_lleno_cm:     float = Field(..., ge=0.0, le=200.0)
    nivel_agua_min_pct: float = Field(..., ge=0.0, le=100.0)

    @model_validator(mode="after")
    def _validar(self):
        if self.temp_vent_off >= self.temp_vent_on:
            raise ValueError("temp_vent_off debe ser menor que temp_vent_on")
        if self.suelo_bomba_off <= self.suelo_bomba_on:
            raise ValueError("suelo_bomba_off debe ser mayor que suelo_bomba_on")
        if self.luz_off_lx <= self.luz_on_lx:
            raise ValueError("luz_off_lx debe ser mayor que luz_on_lx")
        if self.nivel_vacio_cm <= self.nivel_lleno_cm:
            raise ValueError("nivel_vacio_cm debe ser mayor que nivel_lleno_cm")
        return self


class SetpointsInput(SetpointsBase): pass


class SetpointsOutput(SetpointsBase):
    actualizado_en: datetime
    model_config = {"from_attributes": True}


class OverrideInput(BaseModel):
    actuador:      ActuadorLit
    forzar_estado: bool
    duracion_min:  int = Field(..., ge=1, le=240)


class OverrideOutput(BaseModel):
    actuador:           str
    forzar_estado:      bool
    expira_en:          datetime
    creado_en:          datetime
    segundos_restantes: int

    model_config = {"from_attributes": True}


class AlertaOutput(BaseModel):
    id:          int
    timestamp:   datetime
    tipo:        str
    severidad:   str
    titulo:      str
    mensaje:     str
    resuelta:    bool
    resuelta_en: Optional[datetime] = None

    model_config = {"from_attributes": True}


# ---------------------------------------------------------------------------
# 3. DEPENDENCIAS
# ---------------------------------------------------------------------------

def get_db():
    db = SessionLocal()
    try: yield db
    finally: db.close()


def verificar_token(x_device_token: Optional[str] = Header(default=None)):
    if not API_TOKEN: return
    if not x_device_token or x_device_token != API_TOKEN:
        log.warning("Petición rechazada: token ausente o inválido.")
        raise HTTPException(status_code=401, detail="Token inválido o ausente.")


def _override_a_output(o: Override, ahora: datetime) -> OverrideOutput:
    restantes = max(0, int((o.expira_en.replace(tzinfo=timezone.utc) - ahora).total_seconds()))
    return OverrideOutput(
        actuador=o.actuador, forzar_estado=o.forzar_estado,
        expira_en=o.expira_en, creado_en=o.creado_en,
        segundos_restantes=restantes,
    )


# ---------------------------------------------------------------------------
# 4. MOTOR DE ALERTAS
# ---------------------------------------------------------------------------

def _hay_alerta_reciente(db: Session, tipo: str) -> bool:
    """True si ya hay una alerta no resuelta de ese tipo creada en los últimos
    COOLDOWN_ALERTAS_MIN minutos. Evita spamear el mismo aviso."""
    desde = datetime.now(timezone.utc) - timedelta(minutes=COOLDOWN_ALERTAS_MIN)
    existe = (
        db.query(Alerta)
        .filter(
            Alerta.tipo == tipo,
            Alerta.resuelta == False,
            Alerta.timestamp >= desde,
        )
        .first()
    )
    return existe is not None


def _crear_alerta(
    db: Session,
    tipo: str,
    severidad: str,
    titulo: str,
    mensaje: str,
) -> None:
    if _hay_alerta_reciente(db, tipo):
        return
    a = Alerta(
        tipo=tipo, severidad=severidad,
        titulo=titulo, mensaje=mensaje,
    )
    db.add(a)
    db.commit()
    log.warning("ALERTA [%s/%s] %s — %s", severidad.upper(), tipo, titulo, mensaje)


def evaluar_alertas(db: Session, payload: TelemetriaInput, telem_id: int) -> None:
    """
    Llamado al recibir telemetría nueva. Si detecta condiciones críticas,
    crea filas en la tabla `alertas`.
    """
    sp = db.query(Setpoints).filter(Setpoints.id == 1).first()
    nivel_min = sp.nivel_agua_min_pct if sp else 15.0

    # 1) Tanque vacío
    nivel_pct = payload.nivel_agua_pct or 0.0
    if (payload.sensor_nivel_ok is not False) and nivel_pct < nivel_min:
        _crear_alerta(
            db,
            tipo="tanque_vacio",
            severidad="critical",
            titulo="Tanque de agua bajo",
            mensaje=f"Nivel actual {nivel_pct:.0f}% (mínimo {nivel_min:.0f}%). "
                    f"La bomba está bloqueada hasta que rellenes.",
        )

    # 2) Sensor offline (cualquiera)
    sensores_caidos = []
    if payload.sensor_aht_ok   is False: sensores_caidos.append("AHT (temp/hum)")
    if payload.sensor_luz_ok   is False: sensores_caidos.append("BH1750 (luz)")
    if payload.sensor_nivel_ok is False: sensores_caidos.append("HC-SR04 (nivel)")
    if sensores_caidos:
        _crear_alerta(
            db,
            tipo="sensor_offline",
            severidad="warn",
            titulo="Sensor sin respuesta",
            mensaje=f"No responden: {', '.join(sensores_caidos)}. Revisa el cableado.",
        )

    # 3) Temperatura alta sostenida (últimas N lecturas todas > umbral)
    if payload.temperatura > ALERTA_TEMP_ALTA_C:
        ultimas = (
            db.query(Telemetria.temperatura)
            .order_by(Telemetria.id.desc())
            .limit(ALERTA_TEMP_ALTA_N)
            .all()
        )
        if (len(ultimas) >= ALERTA_TEMP_ALTA_N
                and all(t[0] > ALERTA_TEMP_ALTA_C for t in ultimas)):
            _crear_alerta(
                db,
                tipo="temp_alta",
                severidad="warn",
                titulo="Temperatura alta sostenida",
                mensaje=f"Últimas {ALERTA_TEMP_ALTA_N} lecturas con T > {ALERTA_TEMP_ALTA_C}°C "
                        f"(ahora {payload.temperatura:.1f}°C). Riesgo para germinación de café.",
            )

    # 4) Bomba prolongada (ON en últimas N lecturas)
    if payload.estado_bomba:
        ultimas = (
            db.query(Telemetria.estado_bomba)
            .order_by(Telemetria.id.desc())
            .limit(ALERTA_BOMBA_LECTURAS_ON)
            .all()
        )
        if (len(ultimas) >= ALERTA_BOMBA_LECTURAS_ON
                and all(b[0] for b in ultimas)):
            _crear_alerta(
                db,
                tipo="bomba_prolongada",
                severidad="warn",
                titulo="Bomba en marcha prolongada",
                mensaje=f"La bomba lleva al menos {ALERTA_BOMBA_LECTURAS_ON*10}s encendida. "
                        f"Verifica que no haya una fuga o un sensor de humedad atascado.",
            )


# ---------------------------------------------------------------------------
# 5. APP
# ---------------------------------------------------------------------------

app = FastAPI(
    title="Germinador IoT API",
    description="Backend para recibir telemetría del ESP32 y servir estado/setpoints/overrides/alertas.",
    version="1.5.0",
)

if CORS_ORIGINS:
    app.add_middleware(
        CORSMiddleware,
        allow_origins=CORS_ORIGINS,
        allow_credentials=True,
        allow_methods=["GET", "POST", "PUT", "DELETE"],
        allow_headers=["*"],
    )


# ---------------------------------------------------------------------------
# 6. ENDPOINTS — TELEMETRÍA
# ---------------------------------------------------------------------------

@app.post(
    "/api/telemetria",
    response_model=PostResponse, status_code=201,
    summary="Recibe telemetría del ESP32",
    tags=["IoT"], dependencies=[Depends(verificar_token)],
)
def recibir_telemetria(payload: TelemetriaInput, db: Session = Depends(get_db)):
    nuevo = Telemetria(
        temperatura        = payload.temperatura,
        humedad_aire       = payload.humedad_aire,
        humedad_suelo      = payload.humedad_suelo,
        humedad_suelo2     = payload.humedad_suelo2,
        humedad_suelo3     = payload.humedad_suelo3,
        humedad_suelo4     = payload.humedad_suelo4,
        luz_lux            = payload.luz_lux,
        ph_simulado        = payload.ph_simulado,
        estado_bomba       = payload.estado_bomba,
        estado_ventilador  = payload.estado_ventilador,
        estado_ventilador2 = payload.estado_ventilador2,
        bombillo           = payload.bombillo,
        nivel_agua_cm      = payload.nivel_agua_cm or 0.0,
        nivel_agua_pct     = payload.nivel_agua_pct or 0.0,
    )
    db.add(nuevo); db.commit(); db.refresh(nuevo)

    # Evaluación de alertas DESPUÉS de guardar la telemetría
    try:
        evaluar_alertas(db, payload, nuevo.id)
    except Exception as e:
        log.exception("Fallo evaluando alertas: %s", e)

    return PostResponse(mensaje="Registro guardado correctamente.", id=nuevo.id)


@app.get(
    "/api/estado", response_model=TelemetriaOutput,
    summary="Devuelve el último estado del germinador",
    tags=["App"], dependencies=[Depends(verificar_token)],
)
def obtener_ultimo_estado(db: Session = Depends(get_db)):
    ultimo = db.query(Telemetria).order_by(Telemetria.id.desc()).first()
    if ultimo is None:
        raise HTTPException(status_code=404, detail="No hay registros de telemetría.")
    return ultimo


@app.get(
    "/api/historico", response_model=list[TelemetriaOutput],
    summary="Histórico de lecturas",
    tags=["App"], dependencies=[Depends(verificar_token)],
)
def obtener_historico(
    horas: int = Query(24, ge=1, le=720),
    limit: int = Query(500, ge=1, le=5000),
    db: Session = Depends(get_db),
):
    desde = datetime.now(timezone.utc) - timedelta(hours=horas)
    return (
        db.query(Telemetria)
        .filter(Telemetria.timestamp >= desde)
        .order_by(Telemetria.timestamp.asc())
        .limit(limit).all()
    )


# ---------------------------------------------------------------------------
# 7. ENDPOINTS — SETPOINTS
# ---------------------------------------------------------------------------

@app.get(
    "/api/setpoints", response_model=SetpointsOutput,
    tags=["Setpoints"], dependencies=[Depends(verificar_token)],
)
def obtener_setpoints(db: Session = Depends(get_db)):
    sp = db.query(Setpoints).filter(Setpoints.id == 1).first()
    if sp is None:
        sp = Setpoints(id=1); db.add(sp); db.commit(); db.refresh(sp)
    return sp


@app.put(
    "/api/setpoints", response_model=SetpointsOutput,
    tags=["Setpoints"], dependencies=[Depends(verificar_token)],
)
def actualizar_setpoints(payload: SetpointsInput, db: Session = Depends(get_db)):
    sp = db.query(Setpoints).filter(Setpoints.id == 1).first()
    if sp is None:
        sp = Setpoints(id=1); db.add(sp)
    sp.temp_min            = payload.temp_min
    sp.temp_vent_on        = payload.temp_vent_on
    sp.temp_vent_off       = payload.temp_vent_off
    sp.suelo_bomba_on      = payload.suelo_bomba_on
    sp.suelo_bomba_off     = payload.suelo_bomba_off
    sp.luz_on_lx           = payload.luz_on_lx
    sp.luz_off_lx          = payload.luz_off_lx
    sp.nivel_vacio_cm      = payload.nivel_vacio_cm
    sp.nivel_lleno_cm      = payload.nivel_lleno_cm
    sp.nivel_agua_min_pct  = payload.nivel_agua_min_pct
    sp.actualizado_en      = datetime.now(timezone.utc)
    db.commit(); db.refresh(sp)
    log.info("Setpoints actualizados.")
    return sp


# ---------------------------------------------------------------------------
# 8. ENDPOINTS — OVERRIDES
# ---------------------------------------------------------------------------

@app.get(
    "/api/overrides", response_model=list[OverrideOutput],
    tags=["Modo manual"], dependencies=[Depends(verificar_token)],
)
def listar_overrides(db: Session = Depends(get_db)):
    ahora = datetime.now(timezone.utc)
    activos = db.query(Override).filter(Override.expira_en > ahora).all()
    return [_override_a_output(o, ahora) for o in activos]


@app.post(
    "/api/overrides", response_model=OverrideOutput, status_code=201,
    tags=["Modo manual"], dependencies=[Depends(verificar_token)],
)
def crear_override(payload: OverrideInput, db: Session = Depends(get_db)):
    ahora    = datetime.now(timezone.utc)
    expira   = ahora + timedelta(minutes=payload.duracion_min)
    actuador = payload.actuador

    existente = db.query(Override).filter(Override.actuador == actuador).first()
    if existente:
        existente.forzar_estado = payload.forzar_estado
        existente.expira_en     = expira
        existente.creado_en     = ahora
        ov = existente
    else:
        ov = Override(
            actuador=actuador, forzar_estado=payload.forzar_estado,
            expira_en=expira, creado_en=ahora,
        )
        db.add(ov)
    db.commit(); db.refresh(ov)
    log.info("Override %s = %s por %d min", actuador,
             "ON" if payload.forzar_estado else "OFF", payload.duracion_min)
    return _override_a_output(ov, ahora)


@app.delete(
    "/api/overrides/{actuador}", status_code=204,
    tags=["Modo manual"], dependencies=[Depends(verificar_token)],
)
def cancelar_override(
    actuador: ActuadorLit = Path(...),
    db: Session = Depends(get_db),
):
    existente = db.query(Override).filter(Override.actuador == actuador).first()
    if existente:
        db.delete(existente); db.commit()
        log.info("Override de %s cancelado.", actuador)
    return None


# ---------------------------------------------------------------------------
# 9. ENDPOINTS — ALERTAS
# ---------------------------------------------------------------------------

@app.get(
    "/api/alertas", response_model=list[AlertaOutput],
    summary="Lista alertas. Por defecto sólo las no resueltas.",
    tags=["Alertas"], dependencies=[Depends(verificar_token)],
)
def listar_alertas(
    resueltas: bool = Query(False, description="True devuelve TODAS, incluidas resueltas"),
    limit:     int  = Query(100, ge=1, le=500),
    db: Session = Depends(get_db),
):
    q = db.query(Alerta)
    if not resueltas:
        q = q.filter(Alerta.resuelta == False)
    return q.order_by(Alerta.id.desc()).limit(limit).all()


@app.post(
    "/api/alertas/{id}/resolver", response_model=AlertaOutput,
    summary="Marca una alerta como vista/resuelta.",
    tags=["Alertas"], dependencies=[Depends(verificar_token)],
)
def resolver_alerta(id: int = Path(...), db: Session = Depends(get_db)):
    a = db.query(Alerta).filter(Alerta.id == id).first()
    if a is None:
        raise HTTPException(status_code=404, detail="Alerta no encontrada.")
    if not a.resuelta:
        a.resuelta = True
        a.resuelta_en = datetime.now(timezone.utc)
        db.commit(); db.refresh(a)
    return a


@app.delete(
    "/api/alertas/resueltas", status_code=204,
    summary="Borra TODAS las alertas marcadas como resueltas (limpieza).",
    tags=["Alertas"], dependencies=[Depends(verificar_token)],
)
def limpiar_alertas_resueltas(db: Session = Depends(get_db)):
    n = db.query(Alerta).filter(Alerta.resuelta == True).delete()
    db.commit()
    log.info("Limpieza: %d alertas resueltas eliminadas.", n)
    return None


@app.get("/health", tags=["Sistema"])
def health_check():
    return {"status": "ok", "timestamp": datetime.now(timezone.utc).isoformat()}


# ---------------------------------------------------------------------------
# ENTRYPOINT
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=PORT, reload=True)
