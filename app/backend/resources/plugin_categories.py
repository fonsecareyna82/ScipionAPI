from typing import List, Dict, Any

categories = {
  "single_particle": {
    "title": "SPA",
    "description": "SPA processing, classification, refinement and reconstruction"
  },
  "tomography": {
    "title": "Tomography",
    "description": "Tomograms, tilt series and subtomogram workflows"
  },
  "modelling": {
    "title": "Modelling",
    "description": "Model building, fitting, validation and visualization"
  },
  "flexibility": {
    "title": "Flexibility",
    "description": "Visualization and manipulation of flexibility data"
  },
  "chem": {
    "title": "CHEM",
    "description": "CHEMoinformatics and virtual drug screening"
  },
  "unclassified": {
        "title": "Unclassified",
        "description": "Unclassified plugins"
    },
}

plugins = {
    "scipion-em-xmipp": ["single_particle"],
    "scipion-em-relion": ["single_particle"],
    "scipion-em-emready": ["single_particle"],
    "scipion-em-reweighting": ["single_particle"],
    "scipion-em-localrec": ["single_particle"],
    "scipion-em-cryosparc2": ["single_particle"],
    "scipion-em-prody": ["single_particle"],
    "scipion-em-eman": ["single_particle"],
    "scipion-em-resmap": ["single_particle"],
    "scipion-em-eman2": ["single_particle"],
    "scipion-em-appion": ["single_particle"],
    "scipion-em-gautomatch": ["single_particle"],
    "scipion-em-bamfordlab": ["single_particle"],
    "scipion-em-atsas": ["single_particle"],
    "scipion-em-imagic": ["single_particle"],
    "scipion-em-bsoft": ["single_particle"],
    "scipion-em-spider": ["single_particle"],
    "scipion-em-localscale": ["single_particle"],
    "scipion-em-atlas": ["single_particle"],
    "scipion-em-isolde": ["single_particle"],
    "scipion-em-grigoriefflab": ["single_particle"],
    "scipion-em-simple": ["single_particle"],



    "scipion-em-reliontomo": ["tomography"],
    "scipion-em-motioncorr": ["tomography", "single_particle"],
    "scipion-em-tomo": ["tomography"],
    "scipion-em-dynamo": ["tomography"],
    "scipion-em-warp": ["tomography", "single_particle"],
    "scipion-em-aretomo": ["tomography"],
    "scipion-em-topaz": ["tomography"],
    "scipion-em-kiharalab": ["tomography"],
    "scipion-em-gapstop": ["tomography"],
    "scipion-em-imod": ["tomography"],
    "scipion-em-tomo3d": ["tomography"],
    "scipion-em-nextpyp": ["tomography"],
    "scipion-em-emantomo": ["tomography"],
    "scipion-em-cryotiger": ["tomography"],
    "scipion-em-cryodrgn": ["tomography"],
    "scipion-em-crysieve": ["tomography"],
    "scipion-em-membrain": ["tomography"],
    "scipion-em-fidder": ["tomography"],
    "scipion-em-markerfree": ["tomography"],
    "scipion-em-tomosegmemtv": ["tomography"],
    "scipion-em-tardis": ["tomography"],
    "scipion-em-sphire": ["tomography", "single_particle"],
    "scipion-em-novactf": ["tomography"],
    "scipion-em-deepfinder": ["tomography"],
    "scipion-em-cryocare": ["tomography"],
    "scipion-em-miffi": ["tomography"],
    "scipion-em-gctf": ["tomography", "single_particle"],
    "scipion-em-arctic": ["tomography"],
    "scipion-em-gmconvert": ["tomography"],
    "scipion-em-deepdenwedge": ["tomography"],
    "scipion-em-imodfit": ["tomography"],
    "scipion-em-isonet": ["tomography"],
    "scipion-em-emclarity": ["tomography"],
    "scipion-em-rodmus": ["tomography"],
    "scipion-em-cryoassess": ["tomography"],
    "scipion-em-cryoef": ["tomography"],
    "scipion-em-cistem": ["tomography", "single_particle"],
    "scipion-em-spoc": ["tomography"],
    "scipion-em-ais": ["tomography"],
    "scipion-em-teamtomo": ["tomography"],
    "scipion-em-repic": ["tomography"],
    "scipion-em-tomotwin": ["tomography"],
    "scipion-em-susantomo": ["tomography"],
    "scipion-em-sidespitter": ["tomography"],
    "scipion-em-deeppic": ["tomography"],
    "scipion-em-tomoviz": ["tomography"],
    "scipion-em-pyseg": ["tomography"],
    "scipion-em-esrf": ["tomography"],
    "scipion-em-artiax": ["tomography"],
    "scipion-em-pickyolo": ["tomography"],
    "scipion-em-gctffind": ["tomography"],
    "scipion-em-blik": ["tomography"],
    "scipion-em-resem": ["tomography"],
    "scipion-em-clusteralign": ["tomography"],
    "scipion-em-bsofttomo": ["tomography"],
    "scipion-em-surfacemorphometrics": ["tomography"],
    "scipion-em-scf": ["tomography"],
    "scipion-em-epu": ["tomography"],
    "scipion-em-tomoj": ["tomography"],
    "scipion-em-aitom": ["tomography"],
    "scipion-em-xmipptomo": ["tomography"],



    "scipion-em-chimera": ["modelling", "single_particle"],
    "scipion-em-phenix": ["modelling", "single_particle"],
    "scipion-em-modelangelo": ["modelling", "single_particle"],
    "scipion-em-ccp4": ["modelling", "single_particle"],
    "scipion-em-atomstructutils": ["modelling", "single_particle"],
    "scipion-em-carbonara": ["modelling", "single_particle"],
    "scipion-em-esm": ["modelling"],
    "scipion-em-bindcraft": ["modelling"],



    "scipion-em-hax": ["flexibility"],
    "scipion-em-flexutils": ["flexibility"],
    "scipion-em-continuousflex": ["flexibility"],
    "scipion-em-mainmast": ["flexibility"],
    "scipion-em-segger": ["flexibility"],
    "scipion-em-pymol": ["single_particle"],


    "scipion-em-mica": ["chem"],
    "scipion-em-mapq": ["chem"],
    "scipion-em-cryoten": ["chem"],
    "scipion-em-emprot": ["chem"],

    "scipion-em-opusdsd": ["unclassified"],
    "scipion-em-devtools": ["unclassified"],
    "scipion-em-smartscope": ["unclassified"],
    "scipion-em-goctf": ["unclassified"],
    "scipion-em-empiar": ["unclassified"],
    "scipion-em-facilities": ["unclassified"],
    "scipion-em-datamanager": ["unclassified"],
    "scipion-em-workflowhub": ["unclassified"],
    "scipion-em-xmltools": ["unclassified"],
    "scipion-em-powerfit": ["unclassified"],
    "scipion-protein-docking": ["unclassified"],
    "scipion-em-emxlib": ["unclassified"],
    "scipion-em-bioinformatics": ["unclassified"],
    "scipion-em-miplib": ["unclassified"],
    "scipion-em-ccpem": ["unclassified"],
    "scipion-em-ispyb": ["unclassified"],
}


def normalizePluginName(pluginName: str) -> str:
    return str(pluginName or "").strip().lower()


def getPluginCategoryIds(pluginName: str) -> List[str]:
    normalizedName = normalizePluginName(pluginName)
    categoryIds = plugins.get(normalizedName)

    if not categoryIds:
        return ["unclassified"]

    validCategoryIds = [
        categoryId
        for categoryId in categoryIds
        if categoryId in categories
    ]

    return validCategoryIds or ["unclassified"]


def getPluginCategoryData(pluginName: str) -> List[Dict[str, Any]]:
    categoryIds = getPluginCategoryIds(pluginName)

    return [
        {
            "id": categoryId,
            "title": categories[categoryId]["title"],
            "description": categories[categoryId].get("description", ""),
        }
        for categoryId in categoryIds
    ]


def getPluginCategoriesCatalog() -> dict:
    return categories