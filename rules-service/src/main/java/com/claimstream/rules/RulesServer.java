package com.claimstream.rules;

import com.sun.net.httpserver.HttpExchange;
import com.sun.net.httpserver.HttpServer;

import java.io.IOException;
import java.io.OutputStream;
import java.net.InetSocketAddress;
import java.nio.charset.StandardCharsets;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;
import java.util.concurrent.atomic.AtomicLong;

/**
 * REST microservice for rule evaluation.
 *   POST /evaluate  {flat JSON of model features}  -> {"score": 0-100, "rules": [...]}
 *   GET  /health                                     -> {"status":"ok","evaluated":N}
 * Requests are served by a fixed thread pool so concurrent stream workers don't queue behind each other.
 */
public final class RulesServer {

    private static final AtomicLong EVALUATED = new AtomicLong();
    private static final AtomicLong ERRORS = new AtomicLong();

    public static void main(String[] args) throws IOException {
        int port = Integer.parseInt(System.getenv().getOrDefault("PORT", "8090"));
        int threads = Integer.parseInt(System.getenv().getOrDefault("THREADS", "8"));
        HttpServer server = HttpServer.create(new InetSocketAddress("0.0.0.0", port), 256);
        ExecutorService pool = Executors.newFixedThreadPool(threads);
        server.setExecutor(pool);

        server.createContext("/health", ex -> send(ex, 200,
                "{\"status\":\"ok\",\"evaluated\":" + EVALUATED.get() + ",\"errors\":" + ERRORS.get() + "}"));

        server.createContext("/evaluate", ex -> {
            if (!"POST".equals(ex.getRequestMethod())) { send(ex, 405, "{\"error\":\"POST only\"}"); return; }
            try {
                String body = new String(ex.getRequestBody().readAllBytes(), StandardCharsets.UTF_8);
                RulesEngine.Result r = RulesEngine.evaluate(Json.parseObject(body));
                EVALUATED.incrementAndGet();
                send(ex, 200, Json.result(r.score(), r.rules()));
            } catch (IllegalArgumentException e) {
                ERRORS.incrementAndGet();
                send(ex, 400, "{\"error\":\"" + e.getMessage().replace("\"", "'") + "\"}");
            }
        });

        Runtime.getRuntime().addShutdownHook(new Thread(() -> { server.stop(1); pool.shutdown(); }));
        server.start();
        System.out.println("rules-service listening on :" + port + " with " + threads + " threads");
    }

    private static void send(HttpExchange ex, int code, String body) throws IOException {
        byte[] b = body.getBytes(StandardCharsets.UTF_8);
        ex.getResponseHeaders().set("Content-Type", "application/json");
        ex.sendResponseHeaders(code, b.length);
        try (OutputStream os = ex.getResponseBody()) { os.write(b); }
    }
}
