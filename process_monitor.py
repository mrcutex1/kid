import os
import sys
import psutil
import time
import logging
from collections import defaultdict
import asyncio
import tracemalloc
import linecache
from pathlib import Path

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('process_monitor.log'),
        logging.StreamHandler()
    ]
)

class ProcessTracker:
    def __init__(self):
        self.tracked_modules = {
            'call': 'AnonXMusic/core/call.py',
            'thumbnails': 'AnonXMusic/utils/thumbnails.py',
            'youtube': 'AnonXMusic/platforms/Youtube.py',
            'database': 'AnonXMusic/utils/database.py'
        }
        self.module_stats = defaultdict(lambda: {
            'cpu_time': 0,
            'memory': 0,
            'calls': 0,
            'io_read': 0,
            'io_write': 0
        })
        tracemalloc.start()
        self.last_found_pid = None  # Add this to track the last known PID

    async def get_bot_process(self):
        """Find the AnonXMusic process with improved detection"""
        try:
            # First try last known PID
            if self.last_found_pid:
                try:
                    process = psutil.Process(self.last_found_pid)
                    if process.is_running():
                        return process
                except psutil.NoSuchProcess:
                    self.last_found_pid = None

            # Search for process by multiple methods
            for proc in psutil.process_iter(['pid', 'name', 'cmdline', 'cwd']):
                try:
                    # Check multiple conditions
                    cmdline = ' '.join(proc.info['cmdline'] or [])
                    cwd = proc.info['cwd'] if 'cwd' in proc.info else ''
                    
                    if any([
                        'AnonXMusic' in cmdline,
                        'python3 -m AnonXMusic' in cmdline,
                    ]):
                        self.last_found_pid = proc.info['pid']
                        logging.info(f"Found bot process: PID {self.last_found_pid}")
                        return psutil.Process(self.last_found_pid)
                except (psutil.NoSuchProcess, psutil.AccessDenied):
                    continue

            logging.error("Bot process not found - make sure bot is running")
            return None
            
        except Exception as e:
            logging.error(f"Error finding bot process: {e}")
            return None

    def analyze_memory_snapshot(self):
        """Analyze memory usage by file"""
        snapshot = tracemalloc.take_snapshot()
        stats = snapshot.statistics('filename')
        
        for stat in stats:
            file_path = stat.traceback[0].filename
            for module_name, module_path in self.tracked_modules.items():
                if module_path in file_path:
                    self.module_stats[module_name]['memory'] = stat.size / 1024 / 1024  # MB
                    break

    async def monitor_function_calls(self, process):
        """Monitor specific function calls using process memory maps"""
        try:
            with open(f'/proc/{process.pid}/maps', 'r') as maps:
                for line in maps:
                    for module_path in self.tracked_modules.values():
                        if module_path in line:
                            module_name = next(k for k, v in self.tracked_modules.items() if v == module_path)
                            self.module_stats[module_name]['calls'] += 1
        except Exception:
            pass

    async def monitor_io_operations(self, process):
        """Monitor I/O operations per module"""
        try:
            io_counters = process.io_counters()
            # Approximate I/O distribution based on module activity
            for module in self.module_stats:
                if self.module_stats[module]['calls'] > 0:
                    total_calls = sum(m['calls'] for m in self.module_stats.values())
                    ratio = self.module_stats[module]['calls'] / total_calls
                    self.module_stats[module]['io_read'] = io_counters.read_bytes * ratio / 1024 / 1024  # MB
                    self.module_stats[module]['io_write'] = io_counters.write_bytes * ratio / 1024 / 1024  # MB
        except Exception:
            pass

    def log_high_usage(self, module, cpu_percent, memory_mb):
        """Log when a module's resource usage is high"""
        if cpu_percent > 30 or memory_mb > 100:
            logging.warning(f"High resource usage in {module}:")
            logging.warning(f"CPU: {cpu_percent:.1f}% | Memory: {memory_mb:.1f}MB")
            self.log_module_stack_trace(module)

    def log_module_stack_trace(self, module):
        """Log the current stack trace for a specific module"""
        for thread_id, frame in sys._current_frames().items():
            while frame:
                filename = frame.f_code.co_filename
                if self.tracked_modules[module] in filename:
                    line = linecache.getline(filename, frame.f_lineno).strip()
                    logging.warning(f"Stack trace for {module}:")
                    logging.warning(f"File: {filename}")
                    logging.warning(f"Line {frame.f_lineno}: {line}")
                    break
                frame = frame.f_back

    async def monitor_loop(self):
        """Main monitoring loop with improved logging"""
        logging.info("Process monitor starting - waiting for bot process...")
        while True:
            try:
                process = await self.get_bot_process()
                if not process:
                    await asyncio.sleep(5)
                    continue

                logging.info(f"Monitoring bot process (PID: {process.pid})")
                # Monitor CPU per thread
                threads = process.threads()
                for thread in threads:
                    try:
                        thread_cpu = psutil.Process(thread.id).cpu_percent()
                        if thread_cpu > 30:  # High CPU threshold for thread
                            logging.warning(f"High CPU usage in thread {thread.id}: {thread_cpu}%")
                    except psutil.NoSuchProcess:
                        continue

                # Monitor modules
                await self.monitor_function_calls(process)
                await self.monitor_io_operations(process)
                self.analyze_memory_snapshot()

                # Log detailed stats for each module
                for module, stats in self.module_stats.items():
                    logging.info(f"\n{module.upper()} Module Stats:")
                    logging.info(f"Memory Usage: {stats['memory']:.2f}MB")
                    logging.info(f"Function Calls: {stats['calls']}")
                    logging.info(f"I/O Read: {stats['io_read']:.2f}MB")
                    logging.info(f"I/O Write: {stats['io_write']:.2f}MB")
                    
                    self.log_high_usage(module, 
                                      stats.get('cpu_time', 0), 
                                      stats['memory'])

                await asyncio.sleep(60)  # Changed from 300 to 60 seconds (check every minute)

            except Exception as e:
                logging.error(f"Monitoring error: {e}")
                await asyncio.sleep(5)

async def main():
    tracker = ProcessTracker()
    logging.info("Starting process monitor...")
    await tracker.monitor_loop()

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logging.info("Process monitor stopped by user")
