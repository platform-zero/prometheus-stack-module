package org.webservices.testrunner.suites

import io.ktor.client.statement.bodyAsText
import io.ktor.http.HttpStatusCode
import org.webservices.testrunner.framework.*

suspend fun TestRunner.prometheusMonitoringTests() = suite("Prometheus Monitoring Tests") {
test("Prometheus server is healthy") {
        val response = client.getRawResponse("${env.endpoints.prometheus}/-/healthy")
        response.status shouldBe HttpStatusCode.OK
    }

    test("Prometheus can execute PromQL query") {
        val response = client.postRaw("${env.endpoints.prometheus}/api/v1/query?query=up")
        response.status shouldBe HttpStatusCode.OK
        val body = response.bodyAsText()
        body shouldContain "success"
    }

    test("Prometheus targets endpoint responds") {
        val response = client.getRawResponse("${env.endpoints.prometheus}/api/v1/targets")
        response.status shouldBe HttpStatusCode.OK
    }

    test("Prometheus scraping node-exporter") {
        val response = client.postRaw("${env.endpoints.prometheus}/api/v1/query?query=up{job=\"node-exporter\"}")
        response.status shouldBe HttpStatusCode.OK
        val body = response.bodyAsText()
        
        body shouldContain "node-exporter"
        println("      ✓ Prometheus scraping node-exporter")
    }

    test("Prometheus scraping cadvisor") {
        val response = client.postRaw("${env.endpoints.prometheus}/api/v1/query?query=up{job=\"cadvisor\"}")
        response.status shouldBe HttpStatusCode.OK
        val body = response.bodyAsText()
        
        body shouldContain "cadvisor"
        println("      ✓ Prometheus scraping cadvisor")
    }
}
