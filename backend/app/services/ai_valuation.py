import logging
import json
import time
from typing import Dict, Optional
from openai import OpenAI, OpenAIError
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.property import Property
from app.models.ai_analysis_log import AIAnalysisLog

logger = logging.getLogger(__name__)


# Pricing de OpenAI (USD por 1M tokens) - Actualizado a Junio 2026
OPENAI_PRICING = {
    "gpt-4o": {
        "input": 2.50,
        "output": 10.00
    },
    "gpt-4o-mini": {
        "input": 0.15,
        "output": 0.60
    },
    "gpt-4-turbo": {
        "input": 10.00,
        "output": 30.00
    },
    "gpt-3.5-turbo": {
        "input": 0.50,
        "output": 1.50
    }
}


class AIValuationService:
    """
    Servicio para generar valuaciones y observaciones de propiedades usando OpenAI GPT-4o.

    Este servicio proporciona análisis inteligente de propiedades inmobiliarias,
    incluyendo estimaciones de valor de mercado y recomendaciones estratégicas.
    """

    def __init__(self, db: Session):
        self.db = db
        self.client = None

        if settings.OPENAI_API_KEY:
            try:
                self.client = OpenAI(api_key=settings.OPENAI_API_KEY)
            except Exception as e:
                logger.error(f"Error inicializando cliente OpenAI: {e}")
                self.client = None
        else:
            logger.warning("OPENAI_API_KEY no configurada. El servicio de IA no estará disponible.")

    def is_available(self) -> bool:
        """Verifica si el servicio de IA está disponible."""
        return self.client is not None

    def generate_analysis(
        self,
        property_item: Property,
        metrics_data: Dict
    ) -> Optional[Dict]:
        """
        Genera análisis completo de la propiedad (valuación + observaciones).

        Args:
            property_item: Instancia del modelo Property
            metrics_data: Diccionario con métricas calculadas (días en mercado, interacciones, etc.)

        Returns:
            Dict con estructura:
            {
                "valuation": {
                    "estimated_value": float,
                    "confidence": str,
                    "reasoning": str,
                    "price_range": {"min": float, "max": float}
                },
                "observations": {
                    "market_analysis": str,
                    "recommendations": [str, str, str],
                    "risk_level": str,
                    "opportunities": str
                }
            }

            Retorna None si el servicio no está disponible o hay error.
        """
        if not self.is_available():
            logger.warning("Servicio de IA no disponible. Saltando análisis.")
            return None

        try:
            # Generar valuación
            valuation = self._generate_valuation(property_item, metrics_data)

            # Generar observaciones
            observations = self._generate_observations(property_item, metrics_data, valuation)

            return {
                "valuation": valuation,
                "observations": observations
            }

        except OpenAIError as e:
            logger.error(f"Error de OpenAI generando análisis para propiedad {property_item.id}: {e}")
            return None
        except Exception as e:
            logger.exception(f"Error inesperado generando análisis para propiedad {property_item.id}: {e}")
            return None

    def _generate_valuation(
        self,
        property_item: Property,
        metrics_data: Dict
    ) -> Dict:
        """
        Genera valuación de precio usando GPT-4o.

        Args:
            property_item: Propiedad a valuar
            metrics_data: Métricas de la propiedad

        Returns:
            Dict con estimación de valor, confianza y razonamiento
        """
        prompt = self._build_valuation_prompt(property_item, metrics_data)

        logger.info(f"Generando valuación para propiedad {property_item.id}")

        start_time = time.time()

        try:
            response = self.client.chat.completions.create(
                model=settings.OPENAI_MODEL,
                messages=[
                    {
                        "role": "system",
                        "content": (
                            "Eres un experto tasador inmobiliario con 15 años de experiencia en Argentina. "
                            "Tu especialidad es analizar propiedades y estimar valores de mercado realistas "
                            "basándose en ubicación, características, actividad comercial y tendencias del mercado. "
                            "Siempre respondes en formato JSON válido y tus análisis son precisos y fundamentados."
                        )
                    },
                    {"role": "user", "content": prompt}
                ],
                temperature=settings.OPENAI_TEMPERATURE,
                max_tokens=settings.OPENAI_MAX_TOKENS,
                response_format={"type": "json_object"}
            )

            response_time = time.time() - start_time
            content = response.choices[0].message.content
            result = json.loads(content)

            # Registrar log de auditoría
            self._log_analysis(
                property_id=property_item.id,
                analysis_type="valuation",
                prompt=prompt,
                response=content,
                response_obj=response,
                response_time=response_time,
                status="success"
            )

            logger.info(f"Valuación generada exitosamente para propiedad {property_item.id}")

            return result

        except Exception as e:
            response_time = time.time() - start_time

            # Registrar error en log
            self._log_analysis(
                property_id=property_item.id,
                analysis_type="valuation",
                prompt=prompt,
                response=None,
                response_obj=None,
                response_time=response_time,
                status="error",
                error_message=str(e)
            )

            raise

    def _generate_observations(
        self,
        property_item: Property,
        metrics_data: Dict,
        valuation: Dict
    ) -> Dict:
        """
        Genera observaciones y recomendaciones estratégicas.

        Args:
            property_item: Propiedad a analizar
            metrics_data: Métricas de la propiedad
            valuation: Valuación previamente generada

        Returns:
            Dict con análisis de mercado y recomendaciones
        """
        prompt = self._build_observations_prompt(property_item, metrics_data, valuation)

        logger.info(f"Generando observaciones para propiedad {property_item.id}")

        start_time = time.time()

        try:
            response = self.client.chat.completions.create(
                model=settings.OPENAI_MODEL,
                messages=[
                    {
                        "role": "system",
                        "content": (
                            "Eres un asesor comercial inmobiliario estratégico. "
                            "Tu trabajo es analizar el comportamiento de mercado de propiedades, "
                            "identificar oportunidades de mejora y dar recomendaciones accionables "
                            "para optimizar la comercialización. Siempre respondes en formato JSON válido "
                            "con análisis concretos y recomendaciones específicas."
                        )
                    },
                    {"role": "user", "content": prompt}
                ],
                temperature=settings.OPENAI_TEMPERATURE,
                max_tokens=settings.OPENAI_MAX_TOKENS,
                response_format={"type": "json_object"}
            )

            response_time = time.time() - start_time
            content = response.choices[0].message.content
            result = json.loads(content)

            # Registrar log de auditoría
            self._log_analysis(
                property_id=property_item.id,
                analysis_type="observations",
                prompt=prompt,
                response=content,
                response_obj=response,
                response_time=response_time,
                status="success"
            )

            logger.info(f"Observaciones generadas exitosamente para propiedad {property_item.id}")

            return result

        except Exception as e:
            response_time = time.time() - start_time

            # Registrar error en log
            self._log_analysis(
                property_id=property_item.id,
                analysis_type="observations",
                prompt=prompt,
                response=None,
                response_obj=None,
                response_time=response_time,
                status="error",
                error_message=str(e)
            )

            raise

    def _build_valuation_prompt(self, property_item: Property, metrics_data: Dict) -> str:
        """Construye el prompt para valuación."""
        return f"""
Analiza esta propiedad inmobiliaria en Argentina y estima su valor de mercado realista:

DATOS DE LA PROPIEDAD:
- Título: {property_item.title}
- Dirección: {property_item.address}
- Ciudad: {property_item.city}
- Tipo de propiedad: {property_item.property_type}
- Tipo de negocio: {property_item.business_type}
- Precio actual listado: ${float(property_item.price):,.2f}
- Precio justo estimado inicial: ${float(property_item.fair_price):,.2f} (si disponible)
- Estado: {property_item.status}

MÉTRICAS DE COMERCIALIZACIÓN:
- Días en mercado: {metrics_data.get('days_on_market', 0)} días
- Cantidad de bajadas de precio: {metrics_data.get('reductions', 0)}
- Interacciones registradas:
  * Consultas: {metrics_data.get('consultas', 0)}
  * Visitas: {metrics_data.get('visitas', 0)}
  * Interesados: {metrics_data.get('interesados', 0)}
  * Ofertas recibidas: {metrics_data.get('ofertas', 0)}

TAREA:
1. Estima un valor de mercado realista considerando:
   - La ubicación (ciudad y dirección)
   - El tiempo en mercado
   - La actividad de interés (consultas, visitas, ofertas)
   - Las bajadas de precio realizadas
   - El precio actual vs. precio justo estimado

2. Calcula un rango de precio (mínimo y máximo razonable)

3. Asigna un nivel de confianza: "alta", "media" o "baja"

4. Explica tu razonamiento de forma clara y profesional

FORMATO DE RESPUESTA (JSON válido):
{{
  "estimated_value": número (sin símbolos, solo el valor numérico),
  "confidence": "alta" | "media" | "baja",
  "reasoning": "Explicación detallada del análisis en 2-3 párrafos",
  "price_range": {{
    "min": número,
    "max": número
  }}
}}

IMPORTANTE:
- Responde SOLO con JSON válido, sin texto adicional
- Los números deben ser numéricos, no strings
- El reasoning debe ser profesional y fundamentado
"""

    def _build_observations_prompt(
        self,
        property_item: Property,
        metrics_data: Dict,
        valuation: Dict
    ) -> str:
        """Construye el prompt para observaciones."""
        return f"""
Eres un asesor comercial inmobiliario. Analiza el comportamiento de mercado de esta propiedad y genera observaciones estratégicas:

CONTEXTO DE LA PROPIEDAD:
- Título: {property_item.title}
- Ubicación: {property_item.address}, {property_item.city}
- Tipo: {property_item.property_type} - {property_item.business_type}
- Precio actual: ${float(property_item.price):,.2f}
- Valor estimado por IA: ${valuation.get('estimated_value', 0):,.2f}
- Rango de precio sugerido: ${valuation.get('price_range', {}).get('min', 0):,.2f} - ${valuation.get('price_range', {}).get('max', 0):,.2f}

ACTIVIDAD COMERCIAL:
- Días en mercado: {metrics_data.get('days_on_market', 0)}
- Bajadas de precio: {metrics_data.get('reductions', 0)}
- Consultas: {metrics_data.get('consultas', 0)}
- Visitas: {metrics_data.get('visitas', 0)}
- Interesados: {metrics_data.get('interesados', 0)}
- Ofertas: {metrics_data.get('ofertas', 0)}

TAREA:
1. Analiza el comportamiento de mercado (¿está generando interés adecuado? ¿el precio es competitivo?)
2. Identifica 3-4 recomendaciones estratégicas concretas y accionables
3. Evalúa el nivel de riesgo comercial: "bajo", "medio" o "alto"
4. Destaca oportunidades específicas para mejorar la comercialización

FORMATO DE RESPUESTA (JSON válido):
{{
  "market_analysis": "Análisis del comportamiento actual en 2-3 párrafos",
  "recommendations": [
    "Recomendación 1 específica y accionable",
    "Recomendación 2 específica y accionable",
    "Recomendación 3 específica y accionable"
  ],
  "risk_level": "bajo" | "medio" | "alto",
  "opportunities": "Descripción de oportunidades identificadas en 1-2 párrafos"
}}

IMPORTANTE:
- Responde SOLO con JSON válido
- Las recomendaciones deben ser específicas, no genéricas
- El análisis debe ser profesional y orientado a acción
"""

    def _log_analysis(
        self,
        property_id: int,
        analysis_type: str,
        prompt: str,
        response: Optional[str],
        response_obj: Optional[object],
        response_time: float,
        status: str,
        error_message: Optional[str] = None,
        report_id: Optional[int] = None
    ):
        """
        Registra una llamada a la API de OpenAI en la tabla de auditoría.

        Args:
            property_id: ID de la propiedad analizada
            analysis_type: Tipo de análisis ("valuation" o "observations")
            prompt: Prompt enviado a OpenAI
            response: Respuesta en texto (JSON)
            response_obj: Objeto completo de respuesta de OpenAI
            response_time: Tiempo de respuesta en segundos
            status: Estado ("success", "error", "timeout")
            error_message: Mensaje de error si aplica
            report_id: ID del reporte asociado (opcional)
        """
        try:
            # Calcular tokens y costo
            prompt_tokens = None
            completion_tokens = None
            total_tokens = None
            estimated_cost = None

            if response_obj and hasattr(response_obj, 'usage'):
                usage = response_obj.usage
                prompt_tokens = usage.prompt_tokens
                completion_tokens = usage.completion_tokens
                total_tokens = usage.total_tokens

                # Calcular costo estimado
                model_name = settings.OPENAI_MODEL.lower()
                pricing = OPENAI_PRICING.get(model_name, OPENAI_PRICING.get("gpt-4o"))

                if pricing and prompt_tokens and completion_tokens:
                    cost_input = (prompt_tokens / 1_000_000) * pricing["input"]
                    cost_output = (completion_tokens / 1_000_000) * pricing["output"]
                    estimated_cost = cost_input + cost_output

            # Crear registro de log
            log_entry = AIAnalysisLog(
                property_id=property_id,
                report_id=report_id,
                analysis_type=analysis_type,
                model_name=settings.OPENAI_MODEL,
                temperature=float(settings.OPENAI_TEMPERATURE),
                max_tokens=settings.OPENAI_MAX_TOKENS,
                prompt=prompt,
                response=response or "",
                prompt_tokens=prompt_tokens,
                completion_tokens=completion_tokens,
                total_tokens=total_tokens,
                estimated_cost=estimated_cost,
                response_time_seconds=round(response_time, 3),
                status=status,
                error_message=error_message,
                used_in_report=(status == "success")
            )

            self.db.add(log_entry)
            self.db.commit()

            if status == "success" and estimated_cost:
                logger.info(
                    f"Log de IA registrado: {analysis_type} para propiedad {property_id} | "
                    f"Tokens: {total_tokens} | Costo: ${estimated_cost:.6f} | "
                    f"Tiempo: {response_time:.2f}s"
                )
            else:
                logger.warning(
                    f"Log de IA registrado con error: {analysis_type} para propiedad {property_id} | "
                    f"Error: {error_message}"
                )

        except Exception as e:
            # No queremos que un error de logging rompa el flujo principal
            logger.error(f"Error registrando log de IA para propiedad {property_id}: {e}")
            self.db.rollback()

    def _calculate_cost(self, prompt_tokens: int, completion_tokens: int, model: str) -> float:
        """
        Calcula el costo estimado de una llamada a OpenAI.

        Args:
            prompt_tokens: Tokens del prompt
            completion_tokens: Tokens de la respuesta
            model: Nombre del modelo usado

        Returns:
            Costo en USD
        """
        pricing = OPENAI_PRICING.get(model.lower(), OPENAI_PRICING.get("gpt-4o"))

        if not pricing:
            return 0.0

        cost_input = (prompt_tokens / 1_000_000) * pricing["input"]
        cost_output = (completion_tokens / 1_000_000) * pricing["output"]

        return cost_input + cost_output
