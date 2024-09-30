from flask import Flask, request,jsonify, abort, make_response
from databaseManager import DatabaseManager
from cryptoManager import CryptoManager
from configClasses.radConfig import RadConfig
from configClasses.generationConfig import GenerationConfig
import uuid
import os 
import requests
import json

class ControlAgent: 
    
    def __init__(self):
        self.app = Flask(__name__)            
        self.setup_routes()
        self.DBusers = DatabaseManager()
        self.radConfig = RadConfig()
        self.generationConfig = GenerationConfig()
        #self.DBusers.show_database()
        
    def setup_routes(self):
        self.app.add_url_rule('/createNewDatabase', 'createNewDatabase', self.createNewDatabase, methods=['POST'])
        self.app.add_url_rule('/processMessage', 'processMessage', self.process_message, methods=['POST'])
            
    def createNewDatabase(self):
        """
        Creates a new database in the selected RA&D agent .

        This function handles a request to create a new database by verifying the user's 
        credentials, decrypting the provided content, and sending it to a remote system 
        for database creation. It also updates the local user database with the new 
        database information if the operation is successful.

        Process:
            1. Extracts user credentials, encrypted content, and other necessary data from the request.
            2. Verifies user credentials using the local database.
            3. Checks if all required fields are present in the request. If any are missing, returns a 400 error.
            4. Decrypts the provided PDF files and saves them to a temporary directory.
            5. Encrypts the files again with the selected RA&D agent's encryption key.
            6. Prepares the encrypted data and sends it to the remote system for database creation.
            7. If the database is successfully created remotely, extracts the database ID from the response.
            8. Checks if the user already has a database assigned to the specified slot.
                - If a database already exists in the slot, deletes it to avoid leftovers.
            9. Updates the local user database with the new database ID for the specified slot.
            10. Cleans up the temporary directory used to store decrypted files.
    
        Returns:
            Response: A JSON response indicating the status of the database creation. 
                    - 200 OK if successful, including the new database information.
                    - 403 Forbidden if user credentials are invalid.
                    - 400 Bad Request if required fields are missing.
                    - 500 Internal Server Error if the remote request fails.

        Raises:
            HTTPException: Raises a 403 error if the user is not authenticated.

        Request JSON Structure:
            {
                "user": str,                # Username for authentication
                "pass": str,                # Encrypted password for authentication
                "database": str,            # Name of the new database to be created
                "elementNames": str,        # Names of the elements/files, separated by '#'
                "content": str              # Encrypted PDF content, separated by newlines
            }

        Notes:
            - The temporary folder for storing decrypted files is created in the 'controlAgent' directory.
            - The PDF files are decrypted using `CryptoManager.decrypt_pdf` and later re-encrypted 
            using `CryptoManager.encrypt_pdf` before being sent to the remote server.

        """

        encrypted_data = request.get_json()

        if isinstance(encrypted_data, str):
            encrypted_data = json.loads(encrypted_data)

        cipher_text = encrypted_data.get('cipherData')
        decrypted_data = CryptoManager.decrypt_text(cipher_text)
        data = json.loads(decrypted_data)
  
        required_fields = ['user', 'pass', 'database', 'files']
        missing_fields = [field for field in required_fields if data.get(field) is None]

        if missing_fields:
            return jsonify({"error": "Faltan argumentos en el JSON", "missing_fields": missing_fields}), 400

        user = data["user"]
        password = data ["pass"]
        database_slot = data ["database"]
        files = data ["files"]
    
                
        result = self.DBusers.verify_user(user, password)
        
        ## Not auth user
        if (not result):
            abort(403, description="Invalid credentials")
        
        folder_name = str(uuid.uuid4())
        folder_path = os.path.join("controlAgent", folder_name)
        os.makedirs(folder_path)
        
        self.save_pdfs(container=folder_path, files=files)
        
        endpoint = "/createvectordatabase"
        URL = f"{self.radConfig.ip}{endpoint}"
        
        uploadPath = folder_path
        
        filesList = []
        for file in os.listdir(uploadPath):
            filePath = os.path.join(uploadPath, file)
            if os.path.isfile(filePath) and file.lower().endswith('.pdf'):          
                
                with open(filePath, 'rb') as pdf_file:
                    pdf_bytes = pdf_file.read()
                    auxName = file.split(os.sep)
                    name = auxName[-1]
                    file_data = {
                        "title": name,
                        "content": pdf_bytes.hex()  # Almacena las páginas como una lista
                    }
                filesList.append(file_data)

        data = {
            "files": filesList
        }
        
        json_data = json.dumps(data)
        
        cipherData = CryptoManager.encrypt_text(json_data, self.radConfig.cypherPass)
        data_to_send = {"cipherData": cipherData}
        
        response = requests.post(URL, json=data_to_send)

        ##Update users database to include new database 
        if response.status_code == 200:
            #extact data from json
            data = response.json()
            cipherData = data.get("cipherData")
            decrypted_data  = CryptoManager.decrypt_text(cipherData, self.radConfig.cypherPass)
            data = json.loads(decrypted_data)
            database_id = data["database_id"]
            
            #if slot already have a database delete it to avoid leftovers
            database_number = self.get_database_number(database_slot)
            has_assigned = self.DBusers.has_assigned_db(user, database_number)
            if (has_assigned):
                self._delete_database(user=user, database_number=database_number)
                
            self.DBusers.update_databaseID(username=user, database_number=database_number, new_databaseID=database_id)
            self.delete_directory(folder_path)
            
            #No cipher content bc only need to check status code
            response = make_response(jsonify({"Status": "ok"}), 200)
            return response
        else:
            response = make_response(jsonify({"Status": "Fail"}), 500)
            return response


    def _delete_database(self, user, database_number ):   
        """
        Deletes a database from the selected RA&D agent for a specific user and database number.

        Args:
            user (str): The username of the user whose database needs to be deleted.
            database_number (int): The number of the database slot to be deleted.

        Returns:
            None: The function sends the request but does not return a specific response.
        """
        endpoint = "/deletevectordatabase"
        URL = f"{self.radConfig.ip}{endpoint}"  
        
        database_id = self.DBusers.get_database_id_by_user_and_numdb(user, database_number)
    
        data = {
            "database_id": database_id
        }
        
        json_data = json.dumps(data)
        
        cipherData = CryptoManager.encrypt_text(json_data, self.radConfig.cypherPass)
        data_to_send = {"cipherData": cipherData}
        
        requests.post(URL, json=data_to_send)
        
   
   
   
    def process_message(self):

        endpoint = "/getretrievalcontext"
        URL = f"{self.radConfig.ip}{endpoint}"

        encrypted_data = request.get_json()

        if isinstance(encrypted_data, str):
            encrypted_data = json.loads(encrypted_data)

        cipher_text = encrypted_data.get('cipherData')
        decrypted_data = CryptoManager.decrypt_text(cipher_text)
        
        data = json.loads(decrypted_data)
        
        user = data.get('user')
        password = data.get('pass')
        chat = data.get("chat")
        database_slot = data.get("database")
        database_slot_number = self.get_database_number(database_slot)
            
        result = self.DBusers.verify_user(user, password)
        
        if not result:
            abort(403, description="Invalid credentials")
        
        required_fields = ['user', 'pass', 'database', 'chat']
        missing_fields = [field for field in required_fields if data.get(field) is None]

        if missing_fields:
            return jsonify({"error": "Faltan argumentos en el JSON", "missing_fields": missing_fields}), 400


        messages = json.loads(chat)
        database = self.DBusers.get_database_id_by_user_and_numdb(username=user, numdb=database_slot_number)
        
        #Get retrieval of a last user message
        
        last_message = messages[-1].get("text")
            
            #Prepare data to send
        data = {
            "last_message":last_message,
            "database": database
        }
        
        json_data = json.dumps(data)
        cipherData = CryptoManager.encrypt_text(json_data, self.radConfig.cypherPass)
        data_to_send = {"cipherData": cipherData}
        
        context = requests.post(URL, json=data_to_send)
        
            #Get response data
        if context.status_code == 200:
            data = context.json()
            cipher_data = data['cipherData']
            decrypted_data = CryptoManager.decrypt_text(cipher_data, self.radConfig.cypherPass)
              
        else:
            return jsonify({'status': 'Internal Error'}, 500)
            
        ##Generate response from generator Agent

            #Prepare data to send
        data = {
            "chat" : messages,
            "context": decrypted_data
        }
        
        json_data = json.dumps(data)
        cipherData = CryptoManager.encrypt_text(json_data, self.generationConfig.cypherPass)
        data_to_send = {"cipherData": cipherData}

            #Prepare URL
        endpoint = "/generationwithmessagehistory"
        URL = f"{self.generationConfig.ip}{endpoint}"  
           
            #Send
        generation = requests.post(URL, json=data_to_send)
        
        if generation.status_code == 200:
            data = generation.json()  # Parsear la respuesta JSON
            ciphered_generation = data['cipher_response'] 
            generation = CryptoManager.decrypt_text(ciphered_generation, self.generationConfig.cypherPass)
            ciphered_generation = CryptoManager.encrypt_text(generation)
            return jsonify({"cipher_response": ciphered_generation}), 200
            
        return jsonify({'status': 'success', 'message': 'Message processed successfully'})


            
    #Aux functions
    def delete_directory(self, path):
        if os.path.exists(path):            
            if os.path.isdir(path):
                for item in os.listdir(path):
                    item_path = os.path.join(path, item)
                    if os.path.isdir(item_path):
                        self.delete_directory(item_path)
                    else:
                        os.remove(item_path)
                os.rmdir(path) 
    
    
    def get_database_number(self, database_string:str): 
        match database_string: 
            case "db1":
                return 1
            case "db2":
                return 2
            case "db3":
                return 3
            case _: 
                return -1
            
    
    import os

    def save_pdfs(self, container, files):
       
        for file in files:
            file_name = file.get('title')
            
            pdf_bytes = bytes.fromhex(file.get('content'))
            
            file_path = os.path.join(container, file_name)
            
            with open(file_path, 'wb') as pdf_file:
                pdf_file.write(pdf_bytes)

        
    
            
    def run(self):
        self.app.run(port=5006, debug=True)
        
        


if __name__ == '__main__':
    controlAgent = ControlAgent()
    controlAgent.run()