import socket
import json
import hashlib
import struct
import time
import os
import base64
import http.client
import y1

def get_input(prompt, data_type=str):
	while True:
		try:
			value = data_type(input(prompt))
			return value
		except ValueError:
			print(f"Invalid input. Please enter a valid {data_type.__name__}.")

if os.path.isfile('config.json'):
	print("config.json found, start mining")
	with open('config.json','r') as file:
		config = json.load(file)
	connection_type = config.get("connection_type", "stratum")
	pool_address = config['pool_address']
	pool_port = config["pool_port"]
	username = config["user_name"]
	password = config["password"]
	min_diff = config["min_diff"]
	rpc_user = config.get("rpc_user", "")
	rpc_password = config.get("rpc_password", "")
	rpc_port = config.get("rpc_port", 8332)
else:
	print("config.json doesn't exist, generating now")
	connection_type = get_input("Enter connection type (stratum/rpc): ").lower()
	pool_address = get_input("Enter the pool address: ")
	pool_port = get_input("Enter the pool port: ", int)
	username = get_input("Enter the user name: ")
	password = get_input("Enter the password: ")
	min_diff = get_input("Enter the minimum difficulty: ", float)
	
	if connection_type == "rpc":
		rpc_user = get_input("Enter Bitcoin RPC username: ")
		rpc_password = get_input("Enter Bitcoin RPC password: ")
		rpc_port = get_input("Enter Bitcoin RPC port (default 8332): ", int) or 8332
	else:
		rpc_user = ""
		rpc_password = ""
		rpc_port = 8332
	
	config_data = {
		"connection_type": connection_type,
		"pool_address": pool_address,
		"pool_port": pool_port,
		"user_name": username,
		"password": password,
		"min_diff": min_diff,
		"rpc_user": rpc_user,
		"rpc_password": rpc_password,
		"rpc_port": rpc_port
	}
	with open("config.json", "w") as config_file:
		json.dump(config_data, config_file, indent=4)
	print("Configuration data has been written to config.json")

def connect_to_pool(pool_address, pool_port, timeout=30, retries=5):
	for attempt in range(retries):
		try:
			print(f"Attempting to connect to pool (Attempt {attempt + 1}/{retries})...")
			sock = socket.create_connection((pool_address, pool_port), timeout)
			print("Connected to pool!")
			return sock
		except socket.gaierror as e:
			print(f"Address-related error connecting to server: {e}")
		except socket.timeout as e:
			print(f"Connection timed out: {e}")
		except socket.error as e:
			print(f"Socket error: {e}")

		print(f"Retrying in 5 seconds...")
		time.sleep(5)
	
	raise Exception("Failed to connect to the pool after multiple attempts")

def connect_to_bitcoin_rpc(rpc_user, rpc_password, rpc_host="127.0.0.1", rpc_port=8332, timeout=30):
	auth = base64.b64encode(f"{rpc_user}:{rpc_password}".encode()).decode('utf-8')
	headers = {
		"Authorization": f"Basic {auth}",
		"Content-Type": "application/json"
	}
	
	conn = http.client.HTTPConnection(rpc_host, port=rpc_port, timeout=timeout)
	return conn, headers

def send_rpc_request(conn, headers, method, params=None):
	if params is None:
		params = []
	
	payload = {
		"jsonrpc": "1.0",
		"id": "python_miner",
		"method": method,
		"params": params
	}
	
	conn.request("POST", "/", json.dumps(payload), headers)
	response = conn.getresponse()
	data = response.read().decode('utf-8')
	return json.loads(data)

def send_message(sock, message):
	print(f"Sending message: {message}")
	sock.sendall((json.dumps(message) + '\n').encode('utf-8'))

buffer = b''
def receive_messages(sock, timeout=90):
	#buffer = b''
	global buffer
	sock.settimeout(timeout)
	while True:
		try:
			chunk = sock.recv(1024)
			if not chunk:
				break
			buffer += chunk			
			while b'\n' in buffer:
				line, buffer = buffer.split(b'\n', 1)
				print(f"Received message: {line.decode('utf-8')}")
				yield json.loads(line.decode('utf-8'))			
		except socket.timeout:
			print("Receive operation timed out. Retrying...")
			print(len(buffer))
			buffer = b''
			continue

def subscribe(sock):
	message = {
		"id": 1,
		"method": "mining.subscribe",
		"params": ["pyminer/1.2"]
	}
	send_message(sock, message)
	for response in receive_messages(sock):
		if response['id'] == 1:
			print(f"Subscribe response: {response}")
			return response['result']

def authorize(sock, username, password):
	message = {
		"id": 2,
		"method": "mining.authorize",
		"params": [username, password]
	}
	send_message(sock, message)
	for response in receive_messages(sock):
		if response['id'] == 2:
			print(f"Authorize response: {response}")
			return response['result']

def calculate_difficulty(hash_result):
	hash_int = int.from_bytes(hash_result[::-1], byteorder='big')
	max_target = 0xffff * (2**208)
	difficulty = max_target / hash_int
	return difficulty

def mine(job, target, extranonce1, extranonce2_size):
	job_id, prevhash, coinb1, coinb2, merkle_branch, version, nbits, ntime, clean_jobs = job

	extranonce2 = struct.pack('<Q', 0)[:extranonce2_size]
	coinbase = (coinb1 + extranonce1 + extranonce2.hex() + coinb2).encode('utf-8')
	coinbase_hash_bin = hashlib.sha256(hashlib.sha256(coinbase).digest()).digest()
	
	merkle_root = coinbase_hash_bin
	for branch in merkle_branch:
		merkle_root = hashlib.sha256(hashlib.sha256((merkle_root + bytes.fromhex(branch))).digest()).digest()

	block_header = (version + prevhash + merkle_root[::-1].hex() + ntime + nbits).encode('utf-8')
	target_bin = bytes.fromhex(target)[::-1]

	block_time = 60

	exponent = 0x1d
	mantissa = 0x00ffff
	max_target_int = mantissa * (2 ** (8 * (exponent - 3))) #0xFFFF<<216
	max_target_h64 = f"{max_target_int:064x}"
	print(max_target_int)
	print(max_target_h64)

	exponent = int(target[:2], 16)
	mantissa = int(target[2:], 16)
	target_int = mantissa * (2 ** (8 * (exponent - 3)))
	target_h64 = f"{target_int:064x}"
	target_bin = bytes.fromhex(target_h64)
	target_diff = max_target_int/target_int
	target_rate = target_diff * 2**32 / block_time
	print(f"{target_int=}")
	print(f"{target_h64=}")
	print(f"{target_diff=:.8f}")
	print(f"{target_rate/1000=:.2f} KH/s")

	pool_diff = target_diff*0.01
	pool_int = int(max_target_int/pool_diff)
	pool_h64 = f"{pool_int:064x}"
	pool_bin = bytes.fromhex(pool_h64)
	pool_rate = pool_diff * 2**32 / block_time
	print(f"{pool_int=}")
	print(f"{pool_h64=}")
	print(f"{pool_diff=:.8f}")
	print(f"{pool_rate=} H/s")

	import random
	sss = 0x70000000#random.randint(0, 2**32)
	eee = sss + 8000
	
	import time
	start = time.perf_counter()
	for nonce in range(sss, eee):
		nonce_bin = struct.pack('<I', nonce)
		if 1:			
			#print(f"{nonce} : {(block_header + nonce_bin).hex()}")
			hash_result = y1.foo(bytes.fromhex(block_header.decode('ascii')) + nonce_bin)	
		else:
			hash_result = hashlib.sha256(hashlib.sha256(block_header + nonce_bin).digest()).digest()

		hash_result_be = hash_result[::-1]
		if hash_result_be < pool_bin:
			result_int = int.from_bytes(hash_result_be, byteorder='big')
			difficulty = max_target_int / result_int
			print(f"Nonce found: {nonce}, Difficulty: {difficulty:.8f}")
			print(f"Hash: {hash_result_be.hex()}")
			return job_id, extranonce2, ntime, nonce
	end = time.perf_counter()
	print(f"Loop took {end - start:.4f} seconds ({sss}~{eee})")

def submit_solution(sock, job_id, extranonce2, ntime, nonce):
	message = {
		"id": 4,
		"method": "mining.submit",
		"params": [username, job_id, extranonce2.hex(), ntime, struct.pack('<I', nonce).hex()]
	}
	send_message(sock, message)
	for response in receive_messages(sock):
		if response['id'] == 4:
			print("Submission response:", response)
			if response['result'] == False and response['error'][0] == 23:
				print(f"Low difficulty share: {response['error'][2]}")
				return
		else:
			return

def mine_with_rpc():
	try:
		conn, headers = connect_to_bitcoin_rpc(rpc_user, rpc_password, pool_address, rpc_port)
		
		while True:
			template = send_rpc_request(conn, headers, "getblocktemplate", [{"rules": ["segwit"]}])
			if 'error' in template:
				print(f"Error getting block template: {template['error']}")
				time.sleep(30)
				continue
			print("Got block template, mining...")
			time.sleep(10) 
			
	except Exception as e:
		print(f"RPC mining error: {e}")
	finally:
		if 'conn' in locals():
			conn.close()

if __name__ == "__main__":
	if connection_type == "stratum":
		if pool_address.startswith("stratum+tcp://"):
			pool_address = pool_address[len("stratum+tcp://"):]

		while True:
			try:
				sock = connect_to_pool(pool_address, pool_port)
				
				extranonce = subscribe(sock)
				extranonce1, extranonce2_size = extranonce[1], extranonce[2]
				authorize(sock, username, password)
				
				while True:
					for response in receive_messages(sock):
						if response.get('id', 0) == 4:
							print("Submission response:", response)
							if response['result'] == False and response['error'][0] == 23:
								print(f"Low difficulty share: {response['error'][2]}")
						if response.get('method', "") == 'mining.notify':
							job = response['params']
							result = mine(job, job[6], extranonce1, extranonce2_size)
							if result:
								submit_solution(sock, *result)
			except Exception as e:
				print(f"An error occurred: {e}. Reconnecting...")
				time.sleep(5)
	
	elif connection_type == "rpc":
		mine_with_rpc()
	else:
		print(f"Invalid connection type: {connection_type}")
