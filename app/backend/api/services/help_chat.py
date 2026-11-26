"""The help chat: answers a question with what ScipionWeb already knows, never with made-up text.

No language model: the answer is a short sentence and cards, each a real piece of help.
- why a protocol failed: the failure explainer (protocol_failure);
- what usually comes after a protocol: the next-protocol suggestions (Scipion's usage statistics);
- how the project's protocols are: their status;
- anything else: a search over the documentation for users and administrators (resources/help_guide, from
  scipion-docs) and the help of the
  installed protocols and their parameters (help_index), the parameters of the protocol the user is looking at
  first.

The help is in English; a question in Spanish is searched through a small glossary of the field's words, and the
sentence of the answer follows the language of the question.
"""
import json
import logging
import math
import re
import unicodedata
from collections import Counter
from typing import Any, Callable, Dict, Iterable, List, Optional, Tuple

logger = logging.getLogger(__name__)

MAX_QUESTION = 500
MAX_PROTOCOL_CARDS = 4
MAX_PARAM_CARDS = 3
MAX_GUIDE_CARDS = 2
GUIDE_TEXT_CHARS = 900
SUMMARY_CHARS = 420
SUGGESTIONS_TIMEOUT = 6

# Words -----------------------------------------------------------------------------------------------------

STOPWORDS = set("""
a an the of to in on for with and or is are be been am was were how what which who when where do does did i
my me we our you your can could should would will use using used it its this that these those from by as at
there here if so not no yes any some all about into than then also just get got want need please tell show
give know make work works working help protocol protocols prot param parameter parameters option options
el la los las un una unos unas de del al en con por para y o u que como cual cuales cuando donde quien es son
ser estar esta este esto estos estas ese esa eso esos esas aquel mi mis me te se lo le les nos su sus tu tus
hago hacer hace puedo puede pueden debo debe quiero quieres necesito hay tengo tiene ya muy mas sin sobre entre
hasta desde pero si no tambien solo algun alguna algo nada todo todos ver dime decir sirve sirven usar uso
protocolo protocolos parametro parametros opcion opciones valor valores
""".split())

# Spanish words of the field and the English ones the help uses (accents removed, lower case)
GLOSSARY = {
    "movimiento": "motion", "movimientos": "motion", "corregir": "correct correction",
    "correccion": "correction", "alinear": "align alignment", "alineamiento": "alignment",
    "alineacion": "alignment", "alineado": "aligned", "frames": "frames", "fotogramas": "frames",
    "particula": "particle", "particulas": "particles", "picar": "pick picking", "picado": "picking",
    "seleccionar": "select picking", "seleccion": "selection", "escoger": "pick", "extraer": "extract",
    "extraccion": "extraction", "clasificar": "classify classification", "clasificacion": "classification",
    "clases": "classes", "clase": "class", "refinar": "refine refinement", "refinamiento": "refinement",
    "volumen": "volume", "volumenes": "volumes", "mapa": "map", "mapas": "maps", "mascara": "mask",
    "enmascarar": "mask", "resolucion": "resolution", "estimar": "estimate estimation", "estimo": "estimate estimation",
    "estima": "estimate estimation", "calculo": "estimate compute",
    "calcular": "estimate compute",
    "estimacion": "estimation", "desenfoque": "defocus", "micrografia": "micrograph",
    "micrografias": "micrographs", "importar": "import", "tomografia": "tomography",
    "tomograma": "tomogram", "tomogramas": "tomograms", "inclinacion": "tilt", "inclinaciones": "tilt",
    "angulo": "angle", "angulos": "angles", "reconstruir": "reconstruct reconstruction",
    "reconstruccion": "reconstruction", "subtomograma": "subtomogram", "subtomogramas": "subtomograms",
    "promedio": "average", "promediar": "average averaging", "promediado": "averaging", "ruido": "noise",
    "filtro": "filter", "filtrar": "filter", "ganancia": "gain", "dosis": "dose", "ponderacion": "weighting",
    "tamano": "size", "caja": "box", "muestreo": "sampling", "simetria": "symmetry",
    "coordenadas": "coordinates", "coordenada": "coordinate", "modelo": "model", "entrenar": "train training",
    "entrenamiento": "training", "red": "network", "neuronal": "neural", "hilos": "threads",
    "procesadores": "processors mpi", "memoria": "memory", "subconjunto": "subset", "unir": "join union",
    "juntar": "join union", "dividir": "split", "exportar": "export", "ajustar": "fit", "ajuste": "fit fitting",
    "atomico": "atomic", "anisotropico": "anisotropic", "afilar": "sharpen sharpening", "nitidez": "sharpening",
    "validar": "validate validation", "validacion": "validation", "consenso": "consensus",
    "heterogeneidad": "heterogeneity", "flexibilidad": "flexibility", "centrar": "center", "recortar": "crop",
    "reescalar": "rescale", "escalar": "scale rescale", "reducir": "downsample reduce", "invertir": "invert",
    "contraste": "contrast", "normalizar": "normalize", "detener": "stop", "parar": "stop", "cola": "queue",
    "inicial": "initial", "salida": "output", "salidas": "outputs", "entrada": "input", "entradas": "inputs",
    "eliminar": "remove", "quitar": "remove", "malas": "bad", "malos": "bad", "buenas": "good", "calidad": "quality",
    "hielo": "ice", "grosor": "thickness", "cristalino": "crystalline", "agregados": "aggregates",
    "orientacion": "orientation", "orientaciones": "orientations", "proyeccion": "projection",
    "proyecciones": "projections", "rotar": "rotate", "rotacion": "rotation", "voltear": "flip",
    "girar": "rotate", "fase": "phase", "placa": "plate", "aberracion": "aberration", "aberraciones": "aberrations",
    "pulido": "polishing", "pulir": "polish", "bayesiano": "bayesian", "local": "local", "global": "global",
    "pegar": "join", "vecinos": "neighbors", "distancia": "distance", "umbral": "threshold", "limite": "limit",
    "maximo": "maximum", "minimo": "minimum", "numero": "number", "iteraciones": "iterations",
    "iteracion": "iteration", "radio": "radius", "diametro": "diameter", "espesor": "thickness",
    "membrana": "membrane", "membranas": "membranes", "filamento": "filament", "filamentos": "filaments",
    "helicoidal": "helical", "contaminacion": "contamination", "bordes": "edges", "borde": "edge",
    # Using the web
    "corrijo": "correct correction", "corrige": "correct correction", "corregido": "corrected",
    "compartir": "share", "comparto": "share", "paro": "stop", "lanzar": "launch", "lanzo": "launch",
    "ejecutar": "execute run launch", "resultados": "outputs results", "resultado": "output result",
    "veo": "open", "abrir": "open", "abro": "open", "guardar": "save", "guardo": "save", "borrar": "delete",
    "borro": "delete", "renombrar": "rename", "etiquetas": "tags", "etiqueta": "tag", "colas": "queues",
    "maquina": "host", "maquinas": "hosts", "entorno": "environment", "instalar": "install", "instalo": "install",
    "complementos": "plugins", "ajustes": "settings", "configuracion": "settings configuration",
    "configurar": "configure settings", "configuro": "configure settings", "proyecto": "project",
    "proyectos": "projects", "visor": "viewer", "visores": "viewers", "registro": "log", "registros": "logs",
    "usuario": "user", "usuarios": "users", "contrasena": "password", "cuenta": "account",
}

# English words of the field and others the help uses for the same thing
SYNONYMS = {"motion": "alignment drift", "drift": "motion alignment", "denoise": "denoising noise",
            "results": "outputs", "result": "output", "run": "launch execute", "launch": "execute"}

SPANISH_MARKERS = set("""
que como por para el la los las un una del es son hago puedo debo quiero cual cuales donde cuando porque
fallo fallado falla despues siguiente estado esta este hay tengo se mi sirve hacer ayuda hola gracias vale
adios buenas buenos dias tardes noches perfecto genial entendido claro vaya muchas hasta luego
""".split())

# What is said in a chat but asks nothing: answered with a sentence, never searched
SMALL_TALK = {
    "thanks": {"gracias", "thanks", "thank", "thx", "ty", "muchas", "mil", "you", "a", "lot", "much", "so"},
    "greeting": {"hola", "hello", "hi", "hey", "buenas", "buenos", "dias", "tardes", "noches", "good", "morning",
                 "afternoon", "evening"},
    "bye": {"adios", "bye", "goodbye", "chao", "chau", "luego", "hasta", "pronto", "see", "later"},
    "ack": {"ok", "okay", "okey", "vale", "ah", "aha", "oh", "ya", "bien", "bueno", "perfecto", "genial", "great",
            "cool", "nice", "entendido", "claro", "si", "yes", "no", "hmm", "mmm", "eh", "pues", "vaya", "fine",
            "got", "it", "i", "see", "understood", "de", "acuerdo", "nada", "nothing", "muy", "very", "good", "y",
            "and", "lol", "jaja", "jeje", "wow"},
}
SMALL_TALK_ORDER = ("thanks", "bye", "greeting", "ack")


def smallTalk(question: str) -> Optional[str]:
    """The kind of chat sentence a question is (thanks, greeting, bye, ack), or None when it asks something."""
    tokens = re.findall(r"[a-z]+", plain(question))
    if not tokens or len(tokens) > 6:
        return None
    every = set().union(*SMALL_TALK.values())
    if not all(token in every for token in tokens):
        return None
    for kind in SMALL_TALK_ORDER:
        if any(token in SMALL_TALK[kind] for token in tokens) and (kind != "bye" or {"adios", "bye", "goodbye", "chao",
                                                                                     "chau"} & set(tokens)
                                                                  or "hasta" in tokens):
            return kind
    return "ack"

FAILURE_WORDS = {"fallo", "fallado", "falla", "fallan", "fallar", "fallaron", "fallido", "fallidos", "error",
                 "errores", "failed", "fail", "fails", "failure", "crash", "crashed", "broken", "roto", "rompio"}
NEXT_WORDS = {"despues", "siguiente", "siguientes", "next", "after", "luego", "continuar", "continue", "afterwards",
              "sigue", "seguir"}
STATUS_WORDS = {"estado", "status", "running", "corriendo", "ejecutando", "ejecucion", "terminado", "terminados",
                "finished", "progreso", "progress", "marcha", "lanzados", "launched", "queda", "quedan", "va", "van",
                "going"}

# "What happened to #3?": words that ask about a protocol without asking anything in particular
ABOUT_WORDS = {"paso", "pasado", "pasa", "ocurrio", "ocurre", "sucedio", "sucede", "tal", "happened", "happen",
               "happening", "wrong", "mal", "info", "informacion", "cuentame", "dime", "explain", "explica",
               "explicame", "hablame", "sabes", "know", "protocolo", "protocola", "protocol", "prot", "run", "con",
               "sobre", "del", "de", "el", "la", "que", "qu", "le", "ha", "hay", "esta", "going", "va"}

# "How many particles has #6?": counting words, and the kinds of items a protocol makes
COUNT_WORDS = {"many", "much", "cuantos", "cuantas", "cuanto", "cuanta", "numero", "number", "size", "tamano",
               "count", "total"}
OUTPUT_WORDS = {"output", "outputs", "salida", "salidas", "resultado", "resultados", "produced", "produjo", "genero",
                "generated", "made", "obtuvo", "saco", "produce", "producido", "generado", "salieron",
                "salio", "gave", "dio"}
ITEM_KINDS = {
    "particle": ("Particle", "Coordinate"), "particula": ("Particle", "Coordinate"),
    "coordinate": ("Coordinate",), "coordenada": ("Coordinate",), "pick": ("Coordinate",),
    "micrograph": ("Micrograph",), "micrografia": ("Micrograph",), "mic": ("Micrograph",),
    "movie": ("Movie",), "frame": ("Movie",), "ctf": ("CTF",), "class": ("Class",), "clase": ("Class",),
    "average": ("Average", "Class"), "promedio": ("Average", "Class"), "volume": ("Volume",), "volumen": ("Volume",),
    "map": ("Volume",), "mapa": ("Volume",), "tomogram": ("Tomogram",), "tomograma": ("Tomogram",),
    "tilt": ("TiltSeries", "TiltImage"), "subtomogram": ("SubTomogram",), "subtomograma": ("SubTomogram",),
}
ITEM_NAMES = {  # item class → (English, Spanish), plural
    "Particle": ("particles", "partículas"), "Coordinate": ("coordinates", "coordenadas"),
    "Micrograph": ("micrographs", "micrografías"), "Movie": ("movies", "movies"), "CTF": ("CTFs", "CTFs"),
    "Class": ("classes", "clases"), "Average": ("averages", "promedios"), "Volume": ("volumes", "volúmenes"),
    "Tomogram": ("tomograms", "tomogramas"), "TiltSeries": ("tilt series", "series de inclinación"),
    "SubTomogram": ("subtomograms", "subtomogramas"),
}

PROJECT_WORDS = {"proyecto", "project", "como", "how", "going", "todo", "everything"}

PROTOCOL_REFERENCE = re.compile(r"(?:#|\b(?:protocol[oa]?|prot|run)\s*#?\s*)(\d{1,6})\b", re.IGNORECASE)
LOOSE_REFERENCE = re.compile(r"\b(?:el|del|al|con|number|numero|n\.?\s*o)\s+(\d{1,6})\b", re.I)


def plain(text: str) -> str:
    """Lower case, without accents."""
    text = unicodedata.normalize("NFKD", str(text or "").lower())
    return "".join(ch for ch in text if not unicodedata.combining(ch))


def splitCamel(name: str) -> str:
    return re.sub(r"(?<=[a-z0-9])(?=[A-Z])|(?<=[A-Z])(?=[A-Z][a-z])", " ", str(name or ""))


def stem(word: str) -> str:
    for suffix in ("ations", "ation", "ings", "ing", "ions", "ion", "ers", "er", "ed", "es", "s", "e"):
        if word.endswith(suffix) and len(word) - len(suffix) >= 3:
            if suffix == "s" and word.endswith("ss"):
                return word
            return word[:-len(suffix)]
    return word


def words(text: str) -> List[str]:
    return [word for word in re.findall(r"[a-z0-9]+", plain(text)) if word not in STOPWORDS and len(word) > 1]


def terms(text: str) -> List[str]:
    return [stem(word) for word in words(text)]


def queryGroups(question: str) -> List[List[str]]:
    """One group per word of the question: its term and those of its English or synonym words."""
    groups: List[List[str]] = []
    for word in words(question):
        group = [stem(word)]
        for english in GLOSSARY.get(word, "").split() + SYNONYMS.get(word, "").split():
            group.append(stem(english))
            group.extend(stem(synonym) for synonym in SYNONYMS.get(english, "").split())
        group = list(dict.fromkeys(group))
        if group not in groups:
            groups.append(group)
    return groups


def queryTerms(question: str) -> List[str]:
    return list(dict.fromkeys(term for group in queryGroups(question) for term in group))


def isSpanish(question: str) -> bool:
    if re.search(r"[¿¡ñáéíóú]", str(question or "").lower()):
        return True
    tokens = re.findall(r"[a-z]+", plain(question))
    return sum(1 for token in tokens if token in SPANISH_MARKERS) >= 1 and not re.search(
        r"\b(the|what|how|why|which|is|are|do|does)\b", plain(question))


# Search ----------------------------------------------------------------------------------------------------

class Bm25:
    def __init__(self, documents: List[List[str]], k1: float = 1.4, b: float = 0.7):
        self.k1, self.b = k1, b
        self.counts = [Counter(document) for document in documents]
        self.lengths = [len(document) for document in documents]
        self.average = (sum(self.lengths) / len(self.lengths)) if self.lengths else 0.0
        frequency: Counter = Counter()
        for counts in self.counts:
            frequency.update(counts.keys())
        total = len(documents)
        self.idf = {term: math.log(1 + (total - seen + 0.5) / (seen + 0.5)) for term, seen in frequency.items()}

    def scores(self, query: Iterable[str]) -> List[float]:
        query = list(query)
        result = []
        for counts, length in zip(self.counts, self.lengths):
            score = 0.0
            for term in query:
                found = counts.get(term)
                if not found:
                    continue
                norm = self.k1 * (1 - self.b + self.b * length / (self.average or 1))
                score += self.idf.get(term, 0.0) * found * (self.k1 + 1) / (found + norm)
            result.append(score)
        return result


def summaryOf(doc: str, limit: int = SUMMARY_CHARS) -> str:
    """The first paragraph of a description, cut at a sentence when it is long."""
    text = re.split(r"\n\s*\n", str(doc or "").strip(), maxsplit=1)[0]
    text = re.sub(r"\s+", " ", text).strip()
    if len(text) <= limit:
        return text
    cut = text[:limit]
    end = max(cut.rfind(". "), cut.rfind("; "))
    return (cut[:end + 1] if end > limit // 2 else cut.rstrip() + "…").strip()


def protocolDocument(protocol: Dict[str, Any]) -> List[str]:
    label = terms(protocol.get("label", ""))
    name = terms(splitCamel(protocol.get("className", "")))
    return label * 3 + name * 2 + terms(protocol.get("doc", ""))


def protocolTitle(protocol: Dict[str, Any]) -> set:
    return set(terms(protocol.get("label", "")) + terms(splitCamel(protocol.get("className", ""))))


def paramTitle(param: Dict[str, Any]) -> set:
    return set(terms(param.get("label", "")) + terms(splitCamel(param.get("name", ""))))


def paramDocument(param: Dict[str, Any]) -> List[str]:
    return terms(param.get("label", "")) * 2 + terms(splitCamel(param.get("name", ""))) + terms(param.get("help", ""))


def ranked(index: Bm25, groups: List[List[str]], titles: List[set]) -> List[Tuple[int, int, float, int]]:
    """(words of the question found, of them in its title, score, document) of the documents found, best first:
    what has more of the question's words goes first, however often another repeats one of them, and among those
    what has them in its title."""
    scores = index.scores(term for group in groups for term in group)
    found = []
    for position, score in enumerate(scores):
        if score <= 0:
            continue
        counts = index.counts[position]
        covered = sum(1 for group in groups if any(term in counts for term in group))
        inTitle = sum(1 for group in groups if any(term in titles[position] for term in group))
        found.append((covered, inTitle, score, position))
    return sorted(found, reverse=True)


class HelpSearch:
    """The searches over the protocols' help and the user guide, built once per index."""

    def __init__(self, protocols: List[Dict[str, Any]], guide: List[Dict[str, Any]]):
        self.protocols = protocols
        self.protocolIndex = Bm25([protocolDocument(protocol) for protocol in protocols])
        self.params: List[Tuple[Dict[str, Any], Dict[str, Any]]] = [
            (protocol, param) for protocol in protocols for param in protocol.get("params") or []]
        self.paramIndex = Bm25([paramDocument(param) for _, param in self.params])
        self.guide = guide
        self.guideIndex = Bm25([guideDocument(entry) for entry in guide])
        self.protocolTitles = [protocolTitle(protocol) for protocol in protocols]
        self.paramTitles = [paramTitle(param) for _, param in self.params]
        self.guideTitles = [set(terms(entry.get("title", ""))) for entry in guide]

    def protocols_(self, groups, limit: int) -> List[Tuple[int, int, float, Dict[str, Any]]]:
        best, labels = [], set()
        for covered, inTitle, score, index in ranked(self.protocolIndex, groups, self.protocolTitles):
            if len(best) >= limit:
                break
            protocol = self.protocols[index]
            # Variants of a protocol share their label: one card is enough
            if plain(protocol["label"]) in labels:
                continue
            labels.add(plain(protocol["label"]))
            best.append((covered, inTitle, score, protocol))
        return best

    def params_(self, groups, limit: int) -> List[Tuple[int, int, float, Dict[str, Any], Dict[str, Any]]]:
        best, seen = [], set()
        for covered, inTitle, score, index in ranked(self.paramIndex, groups, self.paramTitles):
            if len(best) >= limit:
                break
            protocol, param = self.params[index]
            key = (plain(param["label"]), plain(param.get("help", ""))[:80])
            if key in seen:
                continue
            seen.add(key)
            best.append((covered, inTitle, score, protocol, param))
        return best

    def guide_(self, groups, limit: int) -> List[Tuple[int, int, float, Dict[str, Any]]]:
        return [(covered, inTitle, score, self.guide[index])
                for covered, inTitle, score, index in ranked(self.guideIndex, groups, self.guideTitles)[:limit]]


def paramsOf(protocol: Dict[str, Any], groups, limit: int) -> List[Tuple[int, float, Dict[str, Any]]]:
    params = protocol.get("params") or []
    if not params or not groups:
        return []
    # A small index of its own: the statistics of all the protocols' parameters would favour nothing here
    found = ranked(Bm25([paramDocument(param) for param in params]), groups, [paramTitle(param) for param in params])
    top = found[0][0] if found else 0
    return [(covered, score, params[i]) for covered, _, score, i in found if covered == top][:limit]


def guideDocument(entry: Dict[str, Any]) -> List[str]:
    return terms(entry.get("title", "")) * 3 + terms(entry.get("page", "")) + terms(entry.get("text", ""))


def defaultGuide() -> List[Dict[str, Any]]:
    from app.backend.resources.help_guide import GUIDE

    return GUIDE


_searchCache: Dict[Tuple[int, int], HelpSearch] = {}


def searchFor(protocols: List[Dict[str, Any]], guide: List[Dict[str, Any]]) -> HelpSearch:
    key = (id(protocols), id(guide))
    search = _searchCache.get(key)
    if search is None:
        _searchCache.clear()
        search = _searchCache[key] = HelpSearch(protocols, guide)
    return search


# Cards -----------------------------------------------------------------------------------------------------

def protocolCard(protocol: Dict[str, Any]) -> Dict[str, Any]:
    return {"kind": "protocol", "className": protocol["className"], "label": protocol["label"],
            "summary": summaryOf(protocol.get("doc", "")), "help": protocol.get("doc", "")}


def paramCard(protocol: Dict[str, Any], param: Dict[str, Any]) -> Dict[str, Any]:
    return {"kind": "param", "className": protocol["className"], "protocolLabel": protocol["label"],
            "name": param["name"], "label": param["label"], "help": param.get("help", ""),
            "section": param.get("section", "")}


def guideCard(entry: Dict[str, Any]) -> Dict[str, Any]:
    body = entry.get("text", "")
    if len(body) > GUIDE_TEXT_CHARS:
        cut = body[:GUIDE_TEXT_CHARS]
        body = cut[:cut.rfind("\n")] if cut.rfind("\n") > GUIDE_TEXT_CHARS // 2 else cut.rstrip() + "…"
    return {"kind": "guide", "area": entry.get("area", "user-guide"), "page": entry.get("page", ""),
            "title": entry.get("title", ""), "text": body, "url": entry.get("url", "")}


def projectProtocolRef(row: Dict[str, Any]) -> Dict[str, Any]:
    return {"protocolId": str(row["protocolId"]), "label": row["label"], "status": row["status"]}


# Answers ---------------------------------------------------------------------------------------------------

TEXTS = {
    "found": ("This is what I found in the help:", "Esto es lo que he encontrado en la ayuda:"),
    "paramsOf": ("In the parameters of {label}:", "En los parámetros de {label}:"),
    "alsoFound": ("And in the help of the protocols:", "Y en la ayuda de los protocolos:"),
    "failure": ("This is why {label} failed:", "Por esto ha fallado {label}:"),
    "notFailed": ("{label} did not fail: {status}.", "{label} no ha fallado: {status}."),
    "about": ("{label} (#{id}): {status}.", "{label} (#{id}): {status}."),
    "outputs": ("{label} (#{id}) has these outputs:", "{label} (#{id}) tiene estas salidas:"),
    "noOutputs": ("{label} (#{id}) has no outputs yet: {status}.",
                  "{label} (#{id}) todavía no tiene salidas: {status}."),
    "counted": ("{label} (#{id}) has {count} {what}.", "{label} (#{id}) tiene {count} {what}."),
    "countedIn": ("{label} (#{id}) has {count} {what} in {output}.", "{label} (#{id}) tiene {count} {what} en {output}."),
    "notThatKind": ("{label} (#{id}) made no {what}. These are its outputs:",
                    "{label} (#{id}) no ha generado {what}. Estas son sus salidas:"),
    "pickForOutputs": ("Of which protocol? Select it in the project, or write its number (for example: how many "
                       "particles has #6?).",
                       "¿De qué protocolo? Selecciónalo en el proyecto o escribe su número (por ejemplo: ¿cuántas "
                       "partículas tiene el #6?)."),
    "aboutWhat": ("This is what it does:", "Esto es lo que hace:"),
    "failedList": ("These protocols failed in this project. Ask about one by its number (for example: why did #5 "
                   "fail?) or select it and ask again.",
                   "Estos protocolos han fallado en este proyecto. Pregunta por uno con su número (por ejemplo: ¿por "
                   "qué falló el #5?) o selecciónalo y vuelve a preguntar."),
    "noneFailed": ("No protocol failed in this project.", "Ningún protocolo ha fallado en este proyecto."),
    "next": ("What usually comes after {label}, from what other Scipion users run:",
             "Lo que suele ir después de {label}, según lo que lanzan otros usuarios de Scipion:"),
    "noNext": ("I have no suggestions for {label} now: the suggestions service did not answer or knows none.",
               "Ahora no tengo sugerencias para {label}: el servicio de sugerencias no contesta o no conoce ninguna."),
    "pickProtocol": ("Which protocol? Select it in the project, or write its number (for example: what comes after "
                     "#3?).",
                     "¿Qué protocolo? Selecciónalo en el proyecto o escribe su número (por ejemplo: ¿qué va después "
                     "del #3?)."),
    "status": ("How the protocols of this project are:", "Así están los protocolos de este proyecto:"),
    "statusEmpty": ("This project has no protocols yet.", "Este proyecto todavía no tiene protocolos."),
    "nothing": ("I found nothing about that in the help. Try other words, or the name of a step: motion correction, "
                "CTF, picking, 2D classification…",
                "No he encontrado nada sobre eso en la ayuda. Prueba con otras palabras o con el nombre de un paso: "
                "corrección de movimiento, CTF, picking, clasificación 2D…"),
    "needProject": ("Open a project to ask about its protocols.",
                    "Abre un proyecto para preguntar por sus protocolos."),
    "unknownProtocol": ("There is no protocol {id} in this project.", "No hay ningún protocolo {id} en este proyecto."),
    "thanks": ("You're welcome. Ask me anything else whenever you need it.",
               "De nada. Pregúntame lo que necesites cuando quieras."),
    "greeting": ("Hello! Ask me about a step, a parameter, a protocol that failed or what to run next.",
                 "¡Hola! Pregúntame por un paso, un parámetro, un protocolo que ha fallado o qué lanzar después."),
    "bye": ("Bye! I'll be here if you need me.", "¡Hasta luego! Aquí estaré si me necesitas."),
    "ack": ("Ok. If you have another question, write it here.", "Vale. Si tienes otra duda, escríbela aquí."),
    "empty": ("Ask me about a step, a parameter, a protocol that failed or what to run next.",
              "Pregúntame por un paso, un parámetro, un protocolo que ha fallado o qué lanzar después."),
}


STATUS_PHRASES = {
    "failed": ("it failed", "ha fallado"),
    "finished": ("it finished well", "ha terminado bien"),
    "running": ("it is running", "se está ejecutando"),
    "launched": ("it was launched and is starting", "se ha lanzado y está empezando"),
    "scheduled": ("it is scheduled and waits for the ones before it", "está programado y espera a los anteriores"),
    "aborted": ("it was stopped before it finished", "se paró antes de terminar"),
    "saved": ("it is saved but was never launched", "está guardado pero no se ha lanzado"),
    "interactive": ("it is waiting for you to finish it by hand", "espera a que lo termines a mano"),
}


def statusPhrase(status: str, spanish: bool) -> str:
    known = STATUS_PHRASES.get(str(status or "").lower())
    if known:
        return known[1 if spanish else 0]
    return f"{'su estado es' if spanish else 'its status is'} {status or '?'}"


def itemKindsOf(question: str) -> Tuple[str, ...]:
    """The item classes a question asks about ("particles" → Particle, Coordinate)."""
    found: List[str] = []
    for word in re.findall(r"[a-z0-9]+", plain(question)):
        for candidate in (word, word[:-1], word[:-2], word[:-3]):
            if candidate in ITEM_KINDS:
                found += [kind for kind in ITEM_KINDS[candidate] if kind not in found]
                break
    return tuple(found)


def itemName(className: str, spanish: bool) -> str:
    """'Coordinate2D' → 'coordinates': the plural of what a set holds, in the question's language."""
    for kind, names in ITEM_NAMES.items():
        if kind.lower() in str(className or "").lower():
            return names[1 if spanish else 0]
    return "elementos" if spanish else "items"


def outputType(className: str) -> str:
    """'SetOfCoordinates' → 'Coordinates'."""
    return splitCamel(re.sub(r"^SetOf", "", str(className or ""))).strip() or "?"


def number(value: int, spanish: bool) -> str:
    written = f"{int(value):,}"
    return written.replace(",", ".") if spanish else written


def text(key: str, spanish: bool, **values) -> str:
    return TEXTS[key][1 if spanish else 0].format(**values)


def fetchSuggestions(className: str, timeout: float = SUGGESTIONS_TIMEOUT) -> List[Dict[str, Any]]:
    """[{className, count}] of what Scipion's users run after a protocol class, most run first ([] if unknown)."""
    from urllib.parse import quote
    from urllib.request import urlopen

    from pyworkflow.config import Config

    try:
        raw = json.loads(urlopen(Config.SCIPION_STATS_SUGGESTION % quote(className), timeout=timeout)
                         .read().decode("utf-8"))
    except Exception:
        logger.info("No next-protocol suggestions for %s", className, exc_info=True)
        return []
    found = []
    for item in raw or []:
        try:
            found.append({"className": str(item[0]), "count": int(item[1] or 0)})
        except (TypeError, ValueError, IndexError):
            continue
    return sorted(found, key=lambda item: item["count"], reverse=True)


class HelpChat:
    """answer() with what it needs passed in, so that it is tested without a server."""

    def __init__(self, protocolsHelp: Callable[[], List[Dict[str, Any]]],
                 projectProtocols: Optional[Callable[[], List[Dict[str, Any]]]] = None,
                 explainFailure: Optional[Callable[[str], Dict[str, Any]]] = None,
                 suggestions: Callable[[str], List[Dict[str, Any]]] = fetchSuggestions,
                 guide: Callable[[], List[Dict[str, Any]]] = defaultGuide,
                 protocolOutputs: Optional[Callable[[str], List[Dict[str, Any]]]] = None):
        self.protocolsHelp = protocolsHelp
        self.projectProtocols = projectProtocols
        self.explainFailure = explainFailure
        self.suggestions = suggestions
        self.guide = guide
        self.protocolOutputs = protocolOutputs

    def answer(self, question: str, protocolId: Optional[str] = None) -> Dict[str, Any]:
        question = str(question or "").strip()[:MAX_QUESTION]
        spanish = isSpanish(question)
        if not question:
            return {"text": text("empty", spanish), "cards": []}
        chat = smallTalk(question)
        if chat:
            return {"text": text(chat, spanish), "cards": []}
        flat = plain(question)
        tokens = set(re.findall(r"[a-z]+", flat))
        rows = self.projectProtocols() if self.projectProtocols else None

        referenced = PROTOCOL_REFERENCE.search(question)
        current: Optional[Dict[str, Any]] = None
        if not referenced and rows is not None:
            # "¿qué pasó con el 3?": a bare number counts only when the project has that protocol
            loose = LOOSE_REFERENCE.search(question)
            if loose and any(str(row["protocolId"]) == loose.group(1) for row in rows):
                referenced = loose
        if referenced and rows is not None:
            current = next((row for row in rows if str(row["protocolId"]) == referenced.group(1)), None)
            if current is None:
                return {"text": text("unknownProtocol", spanish, id=referenced.group(1)), "cards": []}
        elif protocolId and rows is not None:
            current = next((row for row in rows if str(row["protocolId"]) == str(protocolId)), None)

        asksFailure = bool(tokens & FAILURE_WORDS) or ("por que" in flat and current is not None
                                                       and current["status"] == "failed")
        asksNext = bool(tokens & NEXT_WORDS)
        asksStatus = bool(tokens & STATUS_WORDS)

        # Without a project, a question about an error that says more than "why did it fail?" is searched
        onlyFailure = len([word for word in words(question) if word not in FAILURE_WORDS | {"why", "porque"}]) <= 1
        if asksFailure and (rows is not None or onlyFailure):
            return self._failure(rows, current, spanish)
        kinds = itemKindsOf(question)
        asksCount = bool(tokens & COUNT_WORDS) and bool(kinds or tokens & OUTPUT_WORDS)
        # "¿Qué salidas tiene?" of the selected one; "where do I see the outputs?" is still for the guide
        onlyOutputs = not [word for word in words(question)
                           if word not in OUTPUT_WORDS | ABOUT_WORDS | {"tiene", "has", "have"} and not word.isdigit()]
        asksOutputs = asksCount or (bool(tokens & OUTPUT_WORDS) and (referenced is not None or onlyOutputs))
        if asksOutputs and rows is not None and not asksNext:
            if current is None:
                return {"text": text("pickForOutputs", spanish), "cards": []}
            return self._outputs(current, kinds, spanish)
        if asksNext:
            return self._next(rows, current, spanish)
        # "How is the project going?": nothing else asked but the status
        rest = [word for word in words(question) if word not in STATUS_WORDS | PROJECT_WORDS]
        if asksStatus and referenced and current is not None:
            return self._about(rows, current, spanish)
        if asksStatus and rows is not None and len(rest) <= 1:
            return self._status(rows, spanish)
        # "What happened to #3?": nothing asked but about the protocol
        if current is not None and not [word for word in words(question)
                                        if word not in ABOUT_WORDS | STATUS_WORDS and not word.isdigit()]:
            return self._about(rows, current, spanish)
        found = self._search(question, current, spanish)
        if not found["cards"] and referenced and current is not None:
            return self._about(rows, current, spanish)
        return found

    # Each kind of answer -----------------------------------------------------------------------------------
    def _failure(self, rows, current, spanish) -> Dict[str, Any]:
        if rows is None:
            return {"text": text("needProject", spanish), "cards": []}
        if current is None:
            failed = [projectProtocolRef(row) for row in rows if row["status"] == "failed"]
            if not failed:
                return {"text": text("noneFailed", spanish), "cards": []}
            return {"text": text("failedList", spanish), "cards": [{"kind": "protocols", "items": failed}]}
        if current["status"] != "failed":
            return {"text": text("notFailed", spanish, label=current["label"], status=statusPhrase(current["status"], spanish)),
                    "cards": []}
        explained = (self.explainFailure(str(current["protocolId"])) if self.explainFailure else None) or {}
        return {"text": text("failure", spanish, label=current["label"]),
                "cards": [dict({"kind": "failure", "protocolId": str(current["protocolId"]),
                                "label": current["label"]}, explained=explained)]}

    def _outputs(self, current, kinds, spanish) -> Dict[str, Any]:
        named = {"label": current["label"], "id": current["protocolId"]}
        rows = self.protocolOutputs(str(current["protocolId"])) if self.protocolOutputs else []
        if not rows:
            return {"text": text("noOutputs", spanish, status=statusPhrase(current["status"], spanish), **named),
                    "cards": []}
        card = {"kind": "outputs", "protocolId": str(current["protocolId"]), "label": current["label"],
                "items": [{"name": row["outputName"], "type": outputType(row.get("setClassName")),
                           "what": itemName(row.get("itemClassName"), spanish) if row.get("itemClassName") else "",
                           "size": None if row.get("size") is None else int(row["size"])} for row in rows]}
        if not kinds:
            return {"text": text("outputs", spanish, **named), "cards": [card]}
        # The asked kind first in the order asked: particles before the coordinates they come from
        matching = []
        for kind in kinds:
            matching += [row for row in rows if row.get("size") is not None and row not in matching
                         and kind.lower() in str(row.get("itemClassName") or "").lower()]
        if not matching:
            return {"text": text("notThatKind", spanish, what=itemName(kinds[0], spanish), **named), "cards": [card]}
        best = matching[0]
        said = text("countedIn" if len(rows) > 1 else "counted", spanish, count=number(best["size"], spanish),
                    what=itemName(best.get("itemClassName"), spanish), output=best["outputName"], **named)
        return {"text": said, "cards": [card] if len(rows) > 1 else []}

    def _about(self, rows, current, spanish) -> Dict[str, Any]:
        if current["status"] == "failed":
            return self._failure(rows, current, spanish)
        said = text("about", spanish, label=current["label"], id=current["protocolId"],
                    status=statusPhrase(current["status"], spanish))
        help_ = next((protocol for protocol in self.protocolsHelp()
                      if protocol["className"] == current["className"]), None)
        if help_ is None:
            return {"text": said, "cards": []}
        return {"text": f"{said} {text('aboutWhat', spanish)}", "cards": [protocolCard(help_)]}

    def _next(self, rows, current, spanish) -> Dict[str, Any]:
        if current is None:
            return {"text": text("needProject" if rows is None else "pickProtocol", spanish), "cards": []}
        found = self.suggestions(current["className"])[:6]
        if not found:
            return {"text": text("noNext", spanish, label=current["label"]), "cards": []}
        installed = {protocol["className"]: protocol for protocol in self.protocolsHelp()}
        items = []
        for item in found:
            protocol = installed.get(item["className"])
            items.append({"className": item["className"], "count": item["count"],
                          "installed": protocol is not None,
                          "label": protocol["label"] if protocol else splitCamel(item["className"]),
                          "summary": summaryOf(protocol.get("doc", "")) if protocol else "",
                          "help": protocol.get("doc", "") if protocol else ""})
        return {"text": text("next", spanish, label=current["label"]),
                "cards": [{"kind": "suggestions", "protocolId": str(current["protocolId"]),
                           "label": current["label"], "items": items}]}

    def _status(self, rows, spanish) -> Dict[str, Any]:
        if not rows:
            return {"text": text("statusEmpty", spanish), "cards": []}
        order = {"failed": 0, "running": 1, "launched": 2, "scheduled": 3, "aborted": 4, "saved": 5, "finished": 6}
        items = sorted((projectProtocolRef(row) for row in rows), key=lambda item: order.get(item["status"], 7))
        return {"text": text("status", spanish), "cards": [{"kind": "protocols", "items": items}]}

    def _search(self, question: str, current, spanish) -> Dict[str, Any]:
        groups = queryGroups(question)
        if not groups:
            return {"text": text("empty", spanish), "cards": []}
        protocols = self.protocolsHelp()
        search = searchFor(protocols, self.guide())
        intro = None
        own: List[Dict[str, Any]] = []
        if current is not None:
            help_ = next((protocol for protocol in protocols if protocol["className"] == current["className"]), None)
            if help_ is not None:
                found = paramsOf(help_, groups, MAX_PARAM_CARDS)
                # Its parameters answer when they have most of the question's words
                if found and found[0][0] >= max(1, len(groups) - 1):
                    intro = text("paramsOf", spanish, label=current["label"])
                    own = [paramCard(help_, param) for _, _, param in found]
        candidates: List[Tuple[int, int, float, Dict[str, Any]]] = []
        candidates += [(covered, inTitle, score, protocolCard(protocol)) for covered, inTitle, score, protocol
                       in search.protocols_(groups, 2 if own else MAX_PROTOCOL_CARDS)]
        candidates += [(covered, inTitle, score, guideCard(entry))
                       for covered, inTitle, score, entry in search.guide_(groups, MAX_GUIDE_CARDS)]
        if not own:
            candidates += [(covered, inTitle, score, paramCard(protocol, param))
                           for covered, inTitle, score, protocol, param in search.params_(groups, 2)]
        if candidates:
            top = max(item[0] for item in candidates)
            # What has fewer of the question's words than the best only blurs the answer
            floor = top if top <= 2 else top - 1
            kept = sorted((item for item in candidates if item[0] >= floor), key=lambda item: item[:3], reverse=True)
            # When some have the question's words in their title, those that have none only mention them
            if kept and max(item[1] for item in kept) >= 1:
                kept = [item for item in kept if item[1] >= 1]
            # A loose parameter only when no protocol or guide section answers as well
            others = [item for item in kept if item[3]["kind"] != "param"]
            params = [item for item in kept if item[3]["kind"] == "param" and (not others or item[:2] > others[0][:2])]
            candidates = params + others
        cards = own + [item[3] for item in candidates]
        if not cards:
            return {"text": text("nothing", spanish), "cards": []}
        return {"text": intro or text("found", spanish), "cards": cards}
