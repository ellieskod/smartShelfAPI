from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from typing import Optional
import os

app = FastAPI()

#weights for confidence score calculation
WEIGHT_SCORE = 1.0
NORMALIZED_SIGNATURE = 2.0
RAW_SIGNATURE = 1.5
CONFIDENCE_THRESHOLD = 0.2

#3 percent margin
MARGIN = 1.03 

#states
baseline_signature = [0, 0, 0, 0]
items = {} 
removed_items = {}
next_id = 1
pending_returns = {}
pending_id_counter = 0
pending_candidates = {} 

#todo: replace with secure token management
TOKEN = os.getenv("API_TOKEN", "devtoken")


#models
class SensorUpdate(BaseModel):
    token: str
    signature: list[float]
    name: Optional[str] = None

class RegisterItem(BaseModel):
    token: str
    item_id: int
    signature: list[float]

class AddItem(BaseModel):
    token: str
    name: str

class Item(BaseModel):
    item_id: int
    name: str
    signature: list[float]
    weight: float

class GetItems(BaseModel):
    token: str

class DeleteItem(BaseModel):
    token: str
    item_id: int



####helpers

def compute_delta(data):
    return [data[i] - baseline_signature[i] for i in range(4)]

def compute_weight(delta):
    return sum(delta)

#euclidean distance on raw signature, same position return
def euclidean_distance(sig1, sig2):
    return sum((sig1[i] - sig2[i])**2 for i in range(4))**0.5

#euclidean distance on normalized signature
def normalized_distance(sig1, sig2):
    norm1 = sum(sig1)
    norm2 = sum(sig2)
    if norm1 == 0 or norm2 == 0:
        return float('inf')
    normalized_sig1 = [sig1[i] / norm1 for i in range(4)]
    normalized_sig2 = [sig2[i] / norm2 for i in range(4)]
    return sum((normalized_sig1[i] - normalized_sig2[i])**2 for i in range(4))**0.5


#confidence score calculation
#combine scores into confidence score. 
def calculate_confidence(delta, item):
    returned_weight = sum(delta)

    #item cannot have higher weight at return (with margin)
    if returned_weight > item["weight"] * MARGIN:
        return 0
    
    weight_score = max(0, 1 - abs(sum(delta) - item["weight"]) / max(abs(item["weight"]), 1))
    normalized_score = max(0, 1 - normalized_distance(delta, item["signature"]) / 10)
    raw_score = max(0, 1 - euclidean_distance(delta, item["signature"]) / 10)
    confidence = (WEIGHT_SCORE * weight_score + NORMALIZED_SIGNATURE * normalized_score + RAW_SIGNATURE * raw_score) / (WEIGHT_SCORE + NORMALIZED_SIGNATURE + RAW_SIGNATURE)
    
    return confidence


def force_resolve():
    #build a score matrix
    assignments = {}
    used_items = set()
    
    #sort all (pending_key, candidate_id) pairs by score descending
    all_pairs = []
    for key, pending in pending_returns.items():
        for candidate_id, score in pending["scores"].items():
            all_pairs.append((score, key, candidate_id))
    all_pairs.sort(reverse=True)
    
    used_keys = set()
    for score, key, candidate_id in all_pairs:
        if key not in used_keys and candidate_id not in used_items:
            assignments[key] = candidate_id
            used_keys.add(key)
            used_items.add(candidate_id)
    
    return assignments

#compare confidence scores for returned items 
def resolve_pending():
    global pending_returns, removed_items, items
    
    if not pending_returns:
        return None
    
    if len(removed_items) == 0:
        return None

    #build best match for each pending return
    assignments = {}
    for key, pending in pending_returns.items():
        best_id = max(pending["scores"], key=lambda id: pending["scores"][id])
        assignments[key] = best_id
    
    #check for conflicts
    assigned_items = list(assignments.values())
    has_conflict = len(assigned_items) != len(set(assigned_items))
    all_returned = len(assignments) == len(removed_items)

    if has_conflict and not all_returned:
        #wait for more returns
        return None  

    #force resolve by best score if all returned, otherwise normal resolve
    if has_conflict:
        assignments = force_resolve()
        
        if not assignments:
            return None

    #finalize
    resolved = []
    for key, match_id in assignments.items():
        delta = pending_returns[key]["delta"]
        weight = compute_weight(delta)
        item = removed_items.pop(match_id)
        item["signature"] = delta
        item["weight"] = weight
        items[match_id] = item
        resolved.append({"item_id": match_id, "name": item["name"], "new_weight": weight})
    
    pending_returns.clear()
    return resolved

#check token
def check_token(token):
    if token != TOKEN:
        raise HTTPException(status_code=401, detail="Invalid token")

#endpoints
@app.get("/")
async def root():
    return {"message": "ok", "status": "200"}

@app.post("/update")
def update(data: SensorUpdate):
    check_token(data.token)
    global baseline_signature, next_id
    delta = compute_delta(data.signature)
    weight = compute_weight(delta)
    baseline_signature = data.signature.copy()

    if weight < 0:
        scores = {id: calculate_confidence([-d for d in delta], item) for id, item in items.items()}
        best_id = max(scores, key=scores.get)
        if scores[best_id] > CONFIDENCE_THRESHOLD:
            removed_items[best_id] = items.pop(best_id)
            return {"event": "removed", "item_id": best_id, "name": removed_items[best_id]["name"]}
        
        return {"event": "removed", "item_id": None, "name": "unknown"}

    #remove
    if weight > 0:
        #single item removed, no matching needed
        if len(removed_items) == 1:
            match_id = list(removed_items.keys())[0]
            item = removed_items.pop(match_id)
            item["signature"] = delta
            item["weight"] = weight
            items[match_id] = item
            return {"event": "returned", "item_id": match_id, "name": items[match_id]["name"], "new_weight": weight}

        #multiple items removed, calculate scores
        scores = {id: calculate_confidence(delta, item) for id, item in removed_items.items()}
        global pending_id_counter
        pending_id_counter += 1
        pending_returns[pending_id_counter] = {"delta": delta, "scores": scores}
        
        #try to resolve all pending returns without conflicts
        resolved = resolve_pending()
        if resolved:
            return {"event": "returned", "resolved": resolved}
   
        return {"event": "pending", "message": "waiting for more returns"}

    #nothing changed
    return {"event": "no_change", "message": "baseline updated", "baseline": baseline_signature}
    
#add new item name to registry
@app.post("/add_item")
def add_item(data: AddItem):
    check_token(data.token)
    global next_id
    global baseline_signature
    item_id = next_id
    next_id += 1
    items[item_id] = {"name": data.name, "signature": baseline_signature.copy(), "weight": 0}
    return {"item_id": item_id, "name": data.name}

#register item with sensor signature and id
@app.post("/register_item")
def register_item(data: RegisterItem):
    check_token(data.token)
    global baseline_signature
    if data.item_id not in items:
        raise HTTPException(status_code=404, detail="Item not found by id")
    item_id = data.item_id
    delta = compute_delta(data.signature)
    weight = compute_weight(delta)
    baseline_signature = data.signature.copy()

    items[item_id]["signature"] = delta
    items[item_id]["weight"] = weight
    return {"item_id": item_id, "name": items[item_id]["name"], "signature": delta, "weight": weight}

#check current state
@app.get("/items")
def get_items(token: str):
    check_token(token)
    return {"items": items, "removed": removed_items, "baseline": baseline_signature}

#completely remove item from registry
@app.post("/delete")
def delete_item(data: DeleteItem):
    check_token(data.token)
    if data.item_id in items:
        del items[data.item_id]
        return {"event": "deleted", "item_id": data.item_id}
    if data.item_id in removed_items:
        del removed_items[data.item_id]
        return {"event": "deleted", "item_id": data.item_id}
    raise HTTPException(status_code=404, detail="Item not found")    