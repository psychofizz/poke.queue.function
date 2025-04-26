import io
import os
import azure.functions as func
import datetime
import json
import logging
import requests
from dotenv import load_dotenv
import pandas as pd
from azure.storage.blob import BlobServiceClient

app = func.FunctionApp()
load_dotenv()

logging.basicConfig( level=logging.INFO )
logger = logging.getLogger(__name__)

DOMAIN = os.getenv("DOMAIN")
AZURE_STORAGE_CONNECTION_STRING = os.getenv("AZURE_STORAGE_CONNECTION_STRING")
BLOB_CONTAINER_NAME = os.getenv("BLOB_CONTAINER_NAME")
STORA_ACCOUNT_NAME = os.getenv("STORA_ACCOUNT_NAME")

@app.queue_trigger(
    arg_name="azqueue"
    , queue_name="requests"
    , connection="QueueAzureWebJobsStorage"
)
def QueueTriggerPokeReport(azqueue: func.QueueMessage):
    body = azqueue.get_body().decode('utf-8')
    record = json.loads(body)
    id = record[0]["id"]

    update_request( id , "inprogress" )
    request_info = get_request(id)
    pokemons = get_pokemons( request_info[0]["type"] )
    pokemon_bytes = generate_csv_to_blob( pokemons )
    blob_name = f"poke_report_{id}.csv"
    upload_csv_to_blob( blob_name=blob_name, csv_data=pokemon_bytes )
    logger.info( f"Archivo {blob_name} se subio con exito" )

    url_completa = f"https://{STORA_ACCOUNT_NAME}.blob.core.windows.net/{BLOB_CONTAINER_NAME}/{blob_name}"
    update_request( id , "completed", url_completa )

def update_request( id: int, status: str, url: str = None ) -> dict:
    payload = {
        "status": status
        , "id": id
    }
    if url:
        payload["url"] = url

    reponse = requests.put( f"{DOMAIN}/api/request" , json=payload )
    return reponse.json()

def get_request(id: int) -> dict:
    reponse = requests.get( f"{DOMAIN}/api/request/{id}"  )
    return reponse.json()


def get_pokemons(type: str, limit: int | None = None) -> list:
    try:
        pokeapi_url = f"https://pokeapi.co/api/v2/type/{type}"
        response = requests.get(pokeapi_url, timeout=10)
        response.raise_for_status()
        data = response.json()
    except requests.exceptions.RequestException as e:
        print(f"Error with the API request: {e}")
        return []
    except ValueError as e:
        print(f"Error parsing response JSON: {e}")
        return []

    pokemon_entries = data.get("pokemon", [])
    
    if limit is not None:
        pokemon_entries = pokemon_entries[:limit]

    pokemons = []

    for entry in pokemon_entries:
        try:
            name = entry["pokemon"]["name"]
            url = f'https://pokeapi.co/api/v2/pokemon/{name}'
            response = requests.get(url, timeout=10)
            response.raise_for_status()
            poke_data = response.json()

            poke_stats = {s['stat']['name']: s['base_stat'] for s in poke_data.get('stats', [])}

            pokemon = {
                "name": name,
                "hp": poke_stats.get("hp"),
                "attack": poke_stats.get("attack"),
                "defense": poke_stats.get("defense"),
                "special-attack": poke_stats.get("special-attack"),
                "special-defense": poke_stats.get("special-defense"),
                "speed": poke_stats.get("speed")
            }
            pokemons.append(pokemon)
        except requests.exceptions.RequestException as e:
            print(f"Error fetching info for Pokémon {name}: {e}")
            continue
        except KeyError as e:
            print(f"Missing info for Pokémon {name}: {e}")
            continue
        except ValueError as e:
            print(f"Error parsing data for Pokémon {name}: {e}")
            continue

    return pokemons


def generate_csv_to_blob( pokemon_list: list ) -> bytes:
    df = pd.DataFrame( pokemon_list )
    output = io.StringIO()
    df.to_csv( output , index=False, encoding='utf-8' )
    csv_bytes = output.getvalue().encode('utf-8')
    output.close()
    return csv_bytes

def upload_csv_to_blob( blob_name: str, csv_data: bytes ):
    try:
        blob_service_client = BlobServiceClient.from_connection_string( AZURE_STORAGE_CONNECTION_STRING)
        blob_client = blob_service_client.get_blob_client( container = BLOB_CONTAINER_NAME, blob=blob_name )
        blob_client.upload_blob( csv_data , overwrite=True )
    except Exception as e:
        logger.error(f"Error al subir el archivo {e} ")
        raise