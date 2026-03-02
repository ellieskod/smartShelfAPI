from fastapi import FastAPI

app = FastAPI()

# states


@app.get("/")
async def root():
    return {"message": "Hello client!"}

@app.get("/newItem/{name}/{signature}")
async def add_item(id: int, name: str, signature: list):
    return { "id": id, "name": name, "signature": signature, "message": f"Item '{name}' with ID {id} added successfully!"}

@app.get("/updateItems/{id}/{signature}")
async def update_item(id: int, signature: list):
    return {"message": f"Item with ID {id} updated successfully!", "id": id, "signature": signature}