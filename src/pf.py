import requests
import os
import json
import binascii
import base64
import struct
import hashlib
import datetime

from Crypto.PublicKey import RSA
from Crypto.Cipher import PKCS1_OAEP

from dotenv import load_dotenv
load_dotenv()  # Load environment variables from .env

TITLE_ID = os.getenv("TITLE_ID")
TITLE_SHARED_SECRET = os.getenv("TITLE_SHARED_SECRET")
PLAYER_SECRET = os.getenv("PLAYER_SECRET")
CUSTOM_ID = os.getenv("CUSTOM_ID")

PLAYFAB_HEADERS = {
    "User-Agent": "libhttpclient/1.0.0.0", 
    "Content-Type": "application/json", 
    "Accept-Language": "en-US"
}

PLAYFAB_SESSION = requests.Session()
PLAYFAB_SESSION.headers.update(PLAYFAB_HEADERS)

PLAYFAB_DOMAIN = f"https://{TITLE_ID.lower()}.playfabapi.com"

def sendPlayFabRequest(endpoint, data, hdrs={}):
    rsp = PLAYFAB_SESSION.post(PLAYFAB_DOMAIN + endpoint, json=data, headers=hdrs).json()
    if rsp['code'] != 200:
        print(rsp)
    else:
        return rsp['data']
 
def getTerrariaCsp():
    return base64.b64decode(sendPlayFabRequest("/Client/GetTitlePublicKey", {
        "TitleId": TITLE_ID,
        "TitleSharedSecret": TITLE_SHARED_SECRET
    })['RSAPublicKey'])
    
def importCspKey(csp):
    e = struct.unpack("I", csp[0x10:0x14])[0]
    n = bytearray(csp[0x14:])
    n.reverse()
    n = int(binascii.hexlify(n), 16)
    return RSA.construct((n, e))

def genPlayFabTimestamp():
    return datetime.datetime.now().isoformat()+"Z"

def genPlayFabSignature(requestBody, timestamp):
    sha256 = hashlib.sha256()
    sha256.update(requestBody.encode("UTF-8") + b"." + timestamp.encode("UTF-8") + b"." + PLAYER_SECRET.encode("UTF-8"))
    return base64.b64encode(sha256.digest())

def LoginWithCustomId():
    customId = os.getenv("CUSTOM_ID")
    playerSecret = os.getenv("PLAYER_SECRET")
    createNewAccount = False

    if customId == None or playerSecret == None:
        createNewAccount = True

    if playerSecret == None:
        createNewAccount = True
    
    payload = {
        "CreateAccount" : None,
        "CustomId": None,
        "EncryptedRequest" : None,
        "InfoRequestParameters" : {
          "GetCharacterInventories" : False,
          "GetCharacterList" : False,
          "GetPlayerProfile" : True,
          "GetPlayerStatistics" : False,
          "GetTitleData" : False,
          "GetUserAccountInfo" : True,
          "GetUserData" : False,
          "GetUserInventory" : False,
          "GetUserReadOnlyData" : False,
          "GetUserVirtualCurrency" : False,
          "PlayerStatisticNames" : None,
          "ProfileConstraints" : None,
          "TitleDataKeys" : None,
          "UserDataKeys" : None,
          "UserReadOnlyDataKeys" : None
        },
        "PlayerSecret" : None,
        "TitleId" : TITLE_ID
    }

    if createNewAccount:
        toEnc = json.dumps({"CustomId":customId, "PlayerSecret": playerSecret}).encode("UTF-8")        
        pubkey = importCspKey(getTerrariaCsp())
        
        cipher_rsa = PKCS1_OAEP.new(pubkey)
        ciphertext = cipher_rsa.encrypt(toEnc)
        
        payload["CreateAccount"] = True
        payload["EncryptedRequest"] = base64.b64encode(ciphertext).decode("UTF-8")

        req = sendPlayFabRequest("/Client/LoginWithCustomID", payload)
    else:
        payload["CustomId"] = customId
        ts = genPlayFabTimestamp()
        sig = genPlayFabSignature(json.dumps(payload), ts)
        req = sendPlayFabRequest("/Client/LoginWithCustomID", payload, {"X-PlayFab-Signature": sig, "X-PlayFab-Timestamp": ts})
    entitytoken = req["EntityToken"]["EntityToken"]
    PLAYFAB_SESSION.headers.update({"X-EntityToken": entitytoken})
    return req
    
def GetEntityToken(playfabId, accType):
    req = sendPlayFabRequest("/Authentication/GetEntityToken", {
       "Entity" : {
          "Id" : playfabId,
          "Type" : accType
       }
    })
    entitytoken = req["EntityToken"]
    PLAYFAB_SESSION.headers.update({"X-EntityToken": entitytoken})
    return req