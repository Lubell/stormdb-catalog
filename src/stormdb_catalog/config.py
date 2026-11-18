"""Server URLs and default paths shared by all stages."""

BASE = "http://stormdb.pet.auh.dk/modules/StormDb"
LIST_URL = BASE + "/projectadmin/listprojects/showExpired/1"
INFO_URL = BASE + "/projectuser/projectinfo/page/0/projectId/{pid}"
# stormdb-python used hyades00.pet.auh.dk/...; override with --extract-url
EXTRACT_URL = BASE + "/extract/"
DEFAULT_LOGIN_FILE = "~/.stormdblogin"
