import asyncio
import os
import signal
import sys
import time
import psutil
import subprocess
from datetime import datetime
import logging
from collections import deque
import shutil
from pathlib import Path

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('watchdog.log'),
        logging.StreamHandler()
    ]
)

class LogMonitor:
    def __init__(self, log_file='logs.txt'):
        self.log_file = log_file
        self.last_position = 0
        self.error_history = deque(maxlen=100)  # Keep last 100 errors
        self.critical_errors = [
            "RuntimeError",
            "ConnectionError",
            "ServerDisconnectedError",
            "ClientConnectorError",
            "socket.send() raised exception"  # Added socket send error
        ]
        self.socket_errors = deque(maxlen=10)  # Track last 10 socket errors

    async def analyze_socket_error(self, error_line):
        """Analyze socket.send() errors for patterns"""
        try:
            # Extract timestamp and context
            timestamp = error_line[:19]  # Assuming format [dd-mm-yyyy HH:MM:SS]
            self.socket_errors.append({
                'timestamp': timestamp,
                'full_error': error_line,
                'count': len(self.socket_errors) + 1
            })
            
            # Analysis of multiple socket errors
            if len(self.socket_errors) >= 3:
                time_diffs = []
                for i in range(len(self.socket_errors) - 1):
                    t1 = datetime.strptime(self.socket_errors[i]['timestamp'], '%d-%m-%Y %H:%M:%S')
                    t2 = datetime.strptime(self.socket_errors[i + 1]['timestamp'], '%d-%m-%Y %H:%M:%S')
                    time_diffs.append((t2 - t1).total_seconds())
                
                # If errors are happening too frequently
                if any(diff < 60 for diff in time_diffs):
                    logging.warning("Multiple socket.send() errors detected in short period")
                    return "frequent_socket_errors"
            
            return None
        except Exception as e:
            logging.error(f"Error analyzing socket error: {e}")
            return None

    async def check_logs(self):
        """Monitor log file for errors with enhanced socket error tracking"""
        try:
            if not os.path.exists(self.log_file):
                return None

            with open(self.log_file, 'r') as f:
                # Seek to last read position
                f.seek(self.last_position)
                new_lines = f.readlines()
                self.last_position = f.tell()

                # Process new lines
                for line in new_lines:
                    if "socket.send() raised exception" in line:
                        self.error_history.append(line.strip())
                        return await self.analyze_socket_error(line.strip())
                    elif "ERROR" in line:
                        self.error_history.append(line.strip())
                        # Check for critical errors
                        if any(err in line for err in self.critical_errors):
                            return line.strip()

            return None

        except Exception as e:
            logging.error(f"Error reading logs: {str(e)}")
            return None

    def get_last_error(self):
        """Get the most recent error from history"""
        return self.error_history[-1] if self.error_history else None

class StorageMonitor:
    def __init__(self, base_path):
        self.base_path = Path(base_path)
        self.downloads_path = self.base_path / 'downloads'
        self.cache_path = self.base_path / 'cache'
        self.min_free_space = 1024 * 1024 * 1024  # 1GB minimum free space

    def check_storage(self):
        """Check storage space and clean if necessary"""
        try:
            total, used, free = shutil.disk_usage(self.base_path)
            free_gb = free / (1024 * 1024 * 1024)
            
            if free < self.min_free_space:
                logging.warning(f"Low storage space: {free_gb:.2f}GB free")
                return False
            return True
        except Exception as e:
            logging.error(f"Storage check error: {e}")
            return False

    def clean_directories(self):
        """Clean downloads and cache directories"""
        try:
            cleaned_size = 0
            for directory in [self.downloads_path, self.cache_path]:
                if directory.exists():
                    size = sum(f.stat().st_size for f in directory.glob('**/*') if f.is_file())
                    shutil.rmtree(directory)
                    directory.mkdir(exist_ok=True)
                    cleaned_size += size
            
            if cleaned_size > 0:
                logging.info(f"Cleaned {cleaned_size / (1024*1024):.2f}MB from downloads/cache")
            return True
        except Exception as e:
            logging.error(f"Error cleaning directories: {e}")
            return False

class CPUMonitor:
    def __init__(self):
        self.high_cpu_history = deque(maxlen=10)  # Track last 10 high CPU readings
        self.cpu_threshold = 80.0
        self.critical_cpu_threshold = 120.0
        self.high_cpu_duration_threshold = 300  # 5 minutes

    def add_cpu_reading(self, cpu_percent, timestamp):
        if cpu_percent > self.cpu_threshold:
            self.high_cpu_history.append({
                'cpu': cpu_percent,
                'time': timestamp
            })

    def should_restart(self):
        if not self.high_cpu_history:
            return False
            
        # If CPU usage is critically high
        if any(reading['cpu'] > self.critical_cpu_threshold for reading in self.high_cpu_history):
            return True

        # If sustained high CPU usage
        if len(self.high_cpu_history) >= 5:
            oldest = self.high_cpu_history[0]['time']
            newest = self.high_cpu_history[-1]['time']
            duration = newest - oldest
            if duration >= self.high_cpu_duration_threshold:
                return True
        
        return False

class BotWatchdog:
    def __init__(self):
        self.bot_process = None
        self.restart_count = 0
        self.max_restarts = 5
        self.restart_interval = 60
        self.last_restart = 0
        self.bot_script = "python3 -m AnonXMusic"
        self.working_dir = os.path.dirname(os.path.abspath(__file__))
        self.log_monitor = LogMonitor()
        self.log_check_interval = 30  # Increased from 10 to 30 seconds
        self.storage_monitor = StorageMonitor(self.working_dir)
        self.storage_check_interval = 900  # Increased from 300 to 900 seconds (15 minutes)
        self.cpu_monitor = CPUMonitor()
        self.last_activity_check = time.time()
        self.activity_timeout = 600  # Increased from 300 to 600 seconds (10 minutes)
        self.force_restart_count = 0
        self.max_force_restarts = 3
        self.force_restart_interval = 3600  # 1 hour

    async def start_bot(self):
        """Start the bot process with cleanup"""
        try:
            self.force_restart_count = 0  # Reset force restart counter
            # Clean up before starting
            self.storage_monitor.clean_directories()

            # Clear old log file
            if os.path.exists('logs.txt'):
                with open('logs.txt', 'w') as f:
                    f.truncate(0)

            self.bot_process = subprocess.Popen(
                self.bot_script.split(),
                cwd=self.working_dir,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                preexec_fn=os.setsid
            )
            logging.info(f"Bot process started with PID: {self.bot_process.pid}")
            return True
        except Exception as e:
            logging.error(f"Failed to start bot: {str(e)}")
            return False

    def kill_bot(self):
        """Kill the bot process and all its children"""
        if not self.bot_process:
            return
        
        try:
            parent = psutil.Process(self.bot_process.pid)
            for child in parent.children(recursive=True):
                child.terminate()
            parent.terminate()
            logging.info(f"Bot process {self.bot_process.pid} terminated")
        except psutil.NoSuchProcess:
            pass
        except Exception as e:
            logging.error(f"Error killing bot process: {str(e)}")
        
        self.bot_process = None

    async def check_bot_activity(self):
        """Check if bot is actually responding and working"""
        try:
            # Check if logs have been updated recently
            if os.path.exists('logs.txt'):
                last_modified = os.path.getmtime('logs.txt')
                if time.time() - last_modified > self.activity_timeout:
                    logging.warning("Bot appears to be frozen (no log activity)")
                    return False
            return True
        except Exception as e:
            logging.error(f"Activity check error: {e}")
            return False

    async def check_bot_health(self):
        """Enhanced health check with CPU monitoring"""
        if not self.bot_process:
            return False

        try:
            process = psutil.Process(self.bot_process.pid)
            if process.status() == psutil.STATUS_ZOMBIE:
                return False

            # Check memory usage
            mem_percent = process.memory_percent()
            if mem_percent > 90:
                logging.warning(f"High memory usage: {mem_percent}%")

            # Enhanced CPU monitoring
            cpu_percent = process.cpu_percent(interval=1)
            current_time = time.time()
            self.cpu_monitor.add_cpu_reading(cpu_percent, current_time)

            if cpu_percent > 80:
                logging.warning(f"High CPU usage: {cpu_percent}%")
                
            # Force restart if CPU usage is problematic
            if self.cpu_monitor.should_restart():
                if current_time - self.last_restart > self.force_restart_interval:
                    if self.force_restart_count < self.max_force_restarts:
                        logging.warning("Forcing restart due to sustained high CPU usage")
                        self.force_restart_count += 1
                        return False
                    else:
                        logging.error("Max force restarts reached due to CPU issues")
                        sys.exit(1)

            # Check bot activity
            if not await self.check_bot_activity():
                logging.warning("Bot activity check failed")
                return False

            return True
        except psutil.NoSuchProcess:
            return False
        except Exception as e:
            logging.error(f"Health check error: {str(e)}")
            return False

    async def monitor_loop(self):
        """Main monitoring loop with enhanced error tracking"""
        log_check_counter = 0
        storage_check_counter = 0
        
        while True:
            try:
                # Reset force restart count periodically
                if time.time() - self.last_restart > 7200:  # 2 hours
                    self.force_restart_count = 0

                # Check storage periodically
                storage_check_counter += 1
                if storage_check_counter >= self.storage_check_interval:
                    storage_check_counter = 0
                    if not self.storage_monitor.check_storage():
                        logging.warning("Low storage space detected, cleaning directories")
                        self.storage_monitor.clean_directories()

                # Check bot health
                if not await self.check_bot_health():
                    # Check logs for errors before restart
                    last_error = self.log_monitor.get_last_error()
                    
                    # Special handling for socket errors
                    if last_error and "socket.send() raised exception" in last_error:
                        logging.warning("Socket send error detected - potential network issue")
                        await asyncio.sleep(5)  # Wait before restart

                    if last_error:
                        logging.warning(f"Last error before crash: {last_error}")
                    
                    current_time = time.time()
                    if current_time - self.last_restart > self.restart_interval:
                        if self.restart_count < self.max_restarts:
                            logging.warning("Bot is not running. Attempting restart...")
                            self.kill_bot()
                            if await self.start_bot():
                                self.restart_count += 1
                                self.last_restart = current_time
                                logging.info(f"Bot restarted. Restart count: {self.restart_count}")
                        else:
                            logging.error("Max restart attempts reached. Manual intervention required.")
                            if last_error:
                                logging.error(f"Final error that caused shutdown: {last_error}")
                            sys.exit(1)
                else:
                    # Check logs periodically
                    log_check_counter += 1
                    if log_check_counter >= self.log_check_interval:
                        log_check_counter = 0
                        critical_error = await self.log_monitor.check_logs()
                        if critical_error:
                            logging.warning(f"Critical error detected: {critical_error}")

                    # Reset restart count if bot has been stable
                    if time.time() - self.last_restart > 3600:
                        self.restart_count = 0
                
                await asyncio.sleep(30)  # Increased from 1 to 30 seconds
                
            except Exception as e:
                logging.error(f"Monitor loop error: {str(e)}")
                await asyncio.sleep(5)

    def handle_signal(self, signum, frame):
        """Handle termination signals"""
        logging.info(f"Received signal {signum}. Shutting down...")
        self.kill_bot()
        sys.exit(0)

    async def run(self):
        """Start the watchdog"""
        signal.signal(signal.SIGTERM, self.handle_signal)
        signal.signal(signal.SIGINT, self.handle_signal)
        
        logging.info("Starting bot watchdog with log monitoring...")
        await self.start_bot()
        await self.monitor_loop()

if __name__ == "__main__":
    watchdog = BotWatchdog()
    try:
        asyncio.run(watchdog.run())
    except KeyboardInterrupt:
        logging.info("Watchdog stopped by user")
        watchdog.kill_bot()
