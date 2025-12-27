import asyncio
import httpx
import time

URL = "http://localhost:8000/api/finance/plans/"
CONCURRENT_REQUESTS = 200  # High concurrency for 50k
TOTAL_REQUESTS = 10000      # 50k requests

async def fetch(client, request_id):
    start_time = time.time()
    try:
        response = await client.get(URL)
        status = response.status_code
        duration = time.time() - start_time
        return status, duration
    except Exception as e:
        return str(e), time.time() - start_time

async def run_test():
    try:
        async with httpx.AsyncClient() as client:
            print(f"Starting Load Test on {URL}")
            print(f"Concurrent: {CONCURRENT_REQUESTS}, Total: {TOTAL_REQUESTS}")
            
            start_time = time.time()
            
            results = []
            for i in range(0, TOTAL_REQUESTS, CONCURRENT_REQUESTS):
                batch = [fetch(client, j) for j in range(i, min(i + CONCURRENT_REQUESTS, TOTAL_REQUESTS))]
                results.extend(await asyncio.gather(*batch))
                
            total_duration = time.time() - start_time
            
            # Stats
            success = [r for r in results if r[0] == 200]
            errors = [r for r in results if r[0] != 200]
            times = [r[1] for r in results if isinstance(r[0], int)]
            
            print("\n" + "="*40)
            print("TEST RESULTS")
            print("="*40)
            print(f"Successful Requests: {len(success)}")
            print(f"Failed Requests:     {len(errors)}")
            if errors:
                print(f"First error sample: {errors[0][0]}")
            print(f"Total Time:          {total_duration:.2f} seconds")
            print(f"Average RPS:         {TOTAL_REQUESTS / total_duration:.2f}")
            if times:
                print(f"Avg Latency:         {sum(times) / len(times)*1000:.2f} ms")
                print(f"Fastest Request:     {min(times)*1000:.2f} ms")
                print(f"Slowest Request:     {max(times)*1000:.2f} ms")
            print("="*40)
    except Exception as e:
        print(f"Test Execution Error: {e}")

if __name__ == "__main__":
    asyncio.run(run_test())
