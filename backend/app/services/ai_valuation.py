import logging
import json
import time
from typing import Dict, Optional
from sqlalchemy.orm import Session
from openai import OpenAIError

from app.core.config import settings
from app.models.property import Property
from app.models.ai_analysis_log import AIAnalysisLog

logger = logging.getLogger(__name__)


# Pricing de OpenAI (USD por 1M tokens)
OPENAI_PRICING = {
    "gpt-4o": {"input": 2.50, "output": 10.00},
    "gpt-4o-mini": {"input": 0.15, "output": 0.60},
    "gpt-4-turbo": {"input": 10.00, "output": 30.00},
    "gpt-3.5-turbo": {"input": 0.50, "output": 1.50}
}

# Pricing de Gemini (USD por 1M tokens)
GEMINI_PRICING = {
    "gemini-1.5-pro": {"input": 1.25, "output": 5.00},
    "gemini-1.5-flash": {"input": 0.075, "output": 0.30},
    "gemini-2.0-flash-exp": {"input": 0.0, "output": 0.0}  # Gratis en preview
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
        self.provider = settings.AI_PROVIDER.lower()

        if self.provider == "openai":
            self._init_openai()
        elif self.provider == "gemini":
            self._init_gemini()
        else:
            logger.error(f"AI_PROVIDER inválido: {settings.AI_PROVIDER}. Usa 'openai' o 'gemini'.")

    def _init_openai(self):
        """Inicializa el cliente de OpenAI."""
        if settings.OPENAI_API_KEY:
            try:
                from openai import OpenAI
                self.client = OpenAI(api_key=settings.OPENAI_API_KEY)
                logger.info(f"OpenAI inicializado: modelo {settings.OPENAI_MODEL}")
            except Exception as e:
                logger.error(f"Error inicializando cliente OpenAI: {e}")
                self.client = None
        else:
            logger.warning("OPENAI_API_KEY no configurada.")

    def _init_gemini(self):
        """Inicializa el cliente de Gemini."""
        if settings.GEMINI_API_KEY:
            try:
                import google.generativeai as genai
                genai.configure(api_key=settings.GEMINI_API_KEY)
                self.client = genai
                logger.info(f"Gemini inicializado: modelo {settings.GEMINI_MODEL}")
            except ImportError:
                logger.error("No se pudo importar google-generativeai. Instala: pip install google-generativeai")
                self.client = None
            except Exception as e:
                logger.error(f"Error inicializando cliente Gemini: {e}")
                self.client = None
        else:
            logger.warning("GEMINI_API_KEY no configurada.")

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

        system_prompt = (
            "Eres un experto tasador inmobiliario con 15 años de experiencia en Argentina. "
            "Tu especialidad es analizar propiedades y estimar valores de mercado realistas "
            "basándose en ubicación, características, actividad comercial y tendencias del mercado. "
            "Siempre respondes en formato JSON válido y tus análisis son precisos y fundamentados."
        )

        try:
            if self.provider == "openai":
                response = self._call_openai(prompt, system_prompt)
            elif self.provider == "gemini":
                response = self._call_gemini(prompt, system_prompt)
            else:
                raise Exception(f"Proveedor no soportado: {self.provider}")

            response_time = time.time() - start_time
            content = response["content"]
            result = json.loads(content)

            # Registrar log de auditoría
            self._log_analysis(
                property_id=property_item.id,
                analysis_type="valuation",
                prompt=prompt,
                response=content,
                response_dict=response,
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
                response_dict=None,
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

        system_prompt = (
            "Eres un asesor comercial inmobiliario estratégico. "
            "Tu trabajo es analizar el comportamiento de mercado de propiedades, "
            "identificar oportunidades de mejora y dar recomendaciones accionables "
            "para optimizar la comercialización. Siempre respondes en formato JSON válido "
            "con análisis concretos y recomendaciones específicas."
        )

        try:
            if self.provider == "openai":
                response = self._call_openai(prompt, system_prompt)
            elif self.provider == "gemini":
                response = self._call_gemini(prompt, system_prompt)
            else:
                raise Exception(f"Proveedor no soportado: {self.provider}")

            response_time = time.time() - start_time
            content = response["content"]
            result = json.loads(content)

            # Registrar log de auditoría
            self._log_analysis(
                property_id=property_item.id,
                analysis_type="observations",
                prompt=prompt,
                response=content,
                response_dict=response,
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
                response_dict=None,
                response_time=response_time,
                status="error",
                error_message=str(e)
            )

            raise

    def _build_valuation_prompt(self, property_item: Property, metrics_data: Dict) -> str:
        """Construye el prompt para valuación."""
        current_price = self._format_money(property_item.price)
        fair_price = self._format_money(property_item.fair_price)
        fair_price_context = (
            "No disponible. No uses un precio justo previo como referencia; "
            "basa la estimación en el precio actual, ubicación y métricas comerciales."
            if property_item.fair_price is None
            else f"{fair_price}. Úsalo solo como referencia interna, no como verdad absoluta."
        )

        return f"""
Analiza esta propiedad inmobiliaria en Argentina y estima su valor de mercado realista:

DATOS DE LA PROPIEDAD:
- Título: {property_item.title}
- Dirección: {property_item.address}
- Ciudad: {property_item.city}
- Tipo de propiedad: {property_item.property_type}
- Tipo de negocio: {property_item.business_type}
- Precio actual listado: {current_price}
- Precio justo estimado inicial: {fair_price_context}
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
        current_price = self._format_money(property_item.price)
        estimated_value = self._format_money(valuation.get("estimated_value"))
        price_range = valuation.get("price_range") or {}
        range_min = self._format_money(price_range.get("min"))
        range_max = self._format_money(price_range.get("max"))

        return f"""
Eres un asesor comercial inmobiliario. Analiza el comportamiento de mercado de esta propiedad y genera observaciones estratégicas:

CONTEXTO DE LA PROPIEDAD:
- Título: {property_item.title}
- Ubicación: {property_item.address}, {property_item.city}
- Tipo: {property_item.property_type} - {property_item.business_type}
- Precio actual: {current_price}
- Valor estimado por IA: {estimated_value}
- Rango de precio sugerido: {range_min} - {range_max}

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

    def _format_money(self, value) -> str:
        """Formatea montos opcionales sin romper cuando el dato no existe."""
        if value is None:
            return "No disponible"

        try:
            return f"${float(value):,.2f}"
        except (TypeError, ValueError):
            return "No disponible"

    def _call_openai(self, prompt: str, system_prompt: str) -> Dict:
        """Llama a OpenAI y retorna respuesta normalizada."""
        response = self.client.chat.completions.create(
            model=settings.OPENAI_MODEL,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": prompt}
            ],
            temperature=settings.OPENAI_TEMPERATURE,
            max_tokens=settings.OPENAI_MAX_TOKENS,
            response_format={"type": "json_object"}
        )

        return {
            "content": response.choices[0].message.content,
            "prompt_tokens": response.usage.prompt_tokens,
            "completion_tokens": response.usage.completion_tokens,
            "total_tokens": response.usage.total_tokens,
            "model": settings.OPENAI_MODEL
        }

    def _call_gemini(self, prompt: str, system_prompt: str) -> Dict:
        """Llama a Gemini y retorna respuesta normalizada."""
        model = self.client.GenerativeModel(
            model_name=settings.GEMINI_MODEL,
            generation_config={
                "temperature": settings.OPENAI_TEMPERATURE,
                "max_output_tokens": settings.OPENAI_MAX_TOKENS,
                "response_mime_type": "application/json"
            },
            system_instruction=system_prompt
        )

        response = model.generate_content(prompt)

        return {
            "content": response.text,
            "prompt_tokens": response.usage_metadata.prompt_token_count,
            "completion_tokens": response.usage_metadata.candidates_token_count,
            "total_tokens": response.usage_metadata.total_token_count,
            "model": settings.GEMINI_MODEL
        }

    def _log_analysis(
        self,
        property_id: int,
        analysis_type: str,
        prompt: str,
        response: Optional[str],
        response_dict: Optional[Dict],
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
            model_used = None

            if response_dict:
                prompt_tokens = response_dict.get("prompt_tokens")
                completion_tokens = response_dict.get("completion_tokens")
                total_tokens = response_dict.get("total_tokens")
                model_used = response_dict.get("model")

                # Calcular costo estimado según proveedor
                if self.provider == "openai":
                    estimated_cost = self._calculate_cost_openai(prompt_tokens, completion_tokens, model_used)
                elif self.provider == "gemini":
                    estimated_cost = self._calculate_cost_gemini(prompt_tokens, completion_tokens, model_used)

            # Crear registro de log
            log_entry = AIAnalysisLog(
                property_id=property_id,
                report_id=report_id,
                analysis_type=analysis_type,
                model_name=model_used or (settings.OPENAI_MODEL if self.provider == "openai" else settings.GEMINI_MODEL),
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

    def _calculate_cost_openai(self, prompt_tokens: int, completion_tokens: int, model: str) -> float:
        """Calcula costo para OpenAI."""
        if not prompt_tokens or not completion_tokens:
            return 0.0

        pricing = OPENAI_PRICING.get(model.lower(), OPENAI_PRICING.get("gpt-4o"))
        cost_input = (prompt_tokens / 1_000_000) * pricing["input"]
        cost_output = (completion_tokens / 1_000_000) * pricing["output"]
        return cost_input + cost_output

    def _calculate_cost_gemini(self, prompt_tokens: int, completion_tokens: int, model: str) -> float:
        """Calcula costo para Gemini."""
        if not prompt_tokens or not completion_tokens:
            return 0.0

        # Normalizar nombre del modelo
        model_key = model.lower()
        if "pro" in model_key and "1.5" in model_key:
            model_key = "gemini-1.5-pro"
        elif "flash" in model_key and "2.0" in model_key:
            model_key = "gemini-2.0-flash-exp"
        elif "flash" in model_key:
            model_key = "gemini-1.5-flash"

        pricing = GEMINI_PRICING.get(model_key, GEMINI_PRICING["gemini-1.5-flash"])
        cost_input = (prompt_tokens / 1_000_000) * pricing["input"]
        cost_output = (completion_tokens / 1_000_000) * pricing["output"]
        return cost_input + cost_output
