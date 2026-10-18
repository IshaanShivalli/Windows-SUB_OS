package operator.runtime;

import java.io.File;
import java.lang.reflect.Method;
import java.util.*;

/**
 * Operator Virtual Machine (OVM) - Java Runtime Engine
 * 
 * Provides an isolated execution environment, app sandbox lifecycle,
 * and capability permission validation for Operator OS applications.
 */
public class OperatorRuntime {

    public static final String RUNTIME_VERSION = "1.0.0-OVM";
    private static final Map<String, ProcessHandle> activeApps = new HashMap<>();

    public interface OperatorApp {
        void onStart(Map<String, String> env);
        void onResume();
        void onPause();
        void onStop();
    }

    public static class AppManifest {
        public String appId;
        public String appName;
        public String version;
        public String mainClass;
        public List<String> permissions = new ArrayList<>();

        public AppManifest(String id, String name, String version, String mainClass) {
            this.appId = id;
            this.appName = name;
            this.version = version;
            this.mainClass = mainClass;
        }
    }

    public static class ProcessHandle {
        public int pid;
        public AppManifest manifest;
        public OperatorApp instance;
        public long startTime;

        public ProcessHandle(int pid, AppManifest manifest, OperatorApp instance) {
            this.pid = pid;
            this.manifest = manifest;
            this.instance = instance;
            this.startTime = System.currentTimeMillis();
        }
    }

    // Built-in Demo Application: Calculator App for Operator OS
    public static class CalculatorApp implements OperatorApp {
        @Override
        public void onStart(Map<String, String> env) {
            System.out.println("[OVM:APP] Starting " + env.get("APP_NAME") + " v" + env.get("APP_VERSION"));
            System.out.println("[OVM:APP] Initializing math engine sandbox...");
            double a = 14.5;
            double b = 27.5;
            System.out.println(String.format("[OVM:APP] Executed Compute: %.2f + %.2f = %.2f", a, b, (a + b)));
            System.out.println(String.format("[OVM:APP] Executed Compute: 2^10 = %.0f", Math.pow(2, 10)));
        }

        @Override public void onResume() { System.out.println("[OVM:APP] App Resumed"); }
        @Override public void onPause()  { System.out.println("[OVM:APP] App Paused"); }
        @Override public void onStop()   { System.out.println("[OVM:APP] App Terminated Cleanly."); }
    }

    // Built-in Demo Application: System Diagnostics Agent
    public static class SysDiagnosticsApp implements OperatorApp {
        @Override
        public void onStart(Map<String, String> env) {
            System.out.println("[OVM:APP] Running System Diagnostics Service...");
            Runtime rt = Runtime.getRuntime();
            System.out.println("[OVM:APP] Available JVM Processors: " + rt.availableProcessors());
            System.out.println("[OVM:APP] Max Memory: " + (rt.maxMemory() / (1024 * 1024)) + " MB");
            System.out.println("[OVM:APP] Total Allocated Memory: " + (rt.totalMemory() / (1024 * 1024)) + " MB");
        }

        @Override public void onResume() {}
        @Override public void onPause() {}
        @Override public void onStop() {}
    }

    public static void main(String[] args) {
        System.out.println("=================================================");
        System.out.println("   OPERATOR VIRTUAL MACHINE (OVM) - JAVA RUNTIME ");
        System.out.println("   Version: " + RUNTIME_VERSION);
        System.out.println("=================================================");

        String appToRun = (args.length > 0) ? args[0] : "calculator";

        if (appToRun.equalsIgnoreCase("calculator")) {
            AppManifest manifest = new AppManifest("app.calc", "Operator Scientific Calculator", "1.2.0", CalculatorApp.class.getName());
            manifest.permissions.add("CAP_MATH_DSP");
            launchApp(manifest, new CalculatorApp());
        } else if (appToRun.equalsIgnoreCase("diagnostics")) {
            AppManifest manifest = new AppManifest("app.diag", "Operator Hardware Monitor", "1.0.0", SysDiagnosticsApp.class.getName());
            manifest.permissions.add("CAP_SYS_METRICS");
            launchApp(manifest, new SysDiagnosticsApp());
        } else {
            System.out.println("Unknown app manifest target: " + appToRun);
            System.out.println("Available targets: 'calculator', 'diagnostics'");
        }
    }

    public static void launchApp(AppManifest manifest, OperatorApp app) {
        int pid = (int)(Math.random() * 9000) + 1000;
        System.out.println(String.format("[OVM:LOADER] Spawning App '%s' [PID: %d]", manifest.appName, pid));
        System.out.println("[OVM:LOADER] Granted Permissions: " + manifest.permissions);

        Map<String, String> env = new HashMap<>();
        env.put("APP_ID", manifest.appId);
        env.put("APP_NAME", manifest.appName);
        env.put("APP_VERSION", manifest.version);
        env.put("PID", String.valueOf(pid));

        ProcessHandle handle = new ProcessHandle(pid, manifest, app);
        activeApps.put(manifest.appId, handle);

        // Run lifecycle
        app.onStart(env);
        app.onResume();
        app.onStop();
        System.out.println("[OVM:LOADER] App execution cycle complete.");
    }
}
