from portaldb.sqletl.runner import Runner, find_first_task, find_task
from portaldb.sqletl import execute, parse, plan
import time

q = 'select * from "https://geo.api.gouv.fr/communes" where ("?codePostal" = 92160 or "?codePostal" = 75008) and population >100000'

#print(execute(q).to_dict())

r = Runner(1)
r.start()
run_id = r.execute(q)
time.sleep(1)
print(r.get(run_id).to_dict())
r.stop()