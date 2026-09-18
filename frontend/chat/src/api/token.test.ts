import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

// The token module keeps module-level state; import fresh in each test.
const importToken = async () => await import("./token");

const TOKEN_URL = "/accounts/token/";
const LOGIN_URL = "/accounts/login/?next=/chat";

function jsonResponse(body: object, status = 200): Response {
  return {
    ok: status >= 200 && status < 300,
    status,
    json: async () => body,
  } as unknown as Response;
}

describe("the access-token module", () => {
  const assign = vi.fn();

  beforeEach(() => {
    vi.resetModules();
    assign.mockClear();
    // jsdom's `window.location` is frozen; stub `fetch`-level behavior instead
    // and intercept navigation at the method the module calls.
    vi.stubGlobal(
      "window",
      Object.assign(Object.create(Object.getPrototypeOf(window)), {
        ...window,
        location: { ...window.location, assign },
      }),
    );
  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("fetches the token with the session cookie", async () => {
    const fetchMock = vi.fn(() =>
      Promise.resolve(jsonResponse({ access: "t1", expires_in: 900 })),
    );
    vi.stubGlobal("fetch", fetchMock);
    const { getAccessToken } = await importToken();

    expect(await getAccessToken()).toBe("t1");
    expect(fetchMock).toHaveBeenCalledWith(TOKEN_URL, { credentials: "include" });
  });

  it("caches the token within the 60s margin", async () => {
    const fetchMock = vi.fn(() =>
      Promise.resolve(jsonResponse({ access: "t1", expires_in: 900 })),
    );
    vi.stubGlobal("fetch", fetchMock);
    const { getAccessToken } = await importToken();

    await getAccessToken();
    await getAccessToken();
    expect(fetchMock).toHaveBeenCalledTimes(1);
  });

  it("re-fetches when the token is within 60s of expiry", async () => {
    const fetchMock = vi.fn(() =>
      Promise.resolve(jsonResponse({ access: "t1", expires_in: 30 })),
    );
    vi.stubGlobal("fetch", fetchMock);
    const { getAccessToken } = await importToken();

    await getAccessToken();
    await getAccessToken();
    expect(fetchMock).toHaveBeenCalledTimes(2);
  });

  it("shares one in-flight promise across concurrent callers", async () => {
    let resolveFetch: (value: Response) => void = () => undefined;
    const fetchMock = vi.fn(
      () =>
        new Promise<Response>((resolve) => {
          resolveFetch = resolve;
        }),
    );
    vi.stubGlobal("fetch", fetchMock);
    const { getAccessToken } = await importToken();

    const first = getAccessToken();
    const second = getAccessToken();
    resolveFetch(jsonResponse({ access: "shared", expires_in: 900 }));
    expect(await Promise.all([first, second])).toEqual(["shared", "shared"]);
    expect(fetchMock).toHaveBeenCalledTimes(1);
  });

  it("redirects to the login page on a 401", async () => {
    vi.stubGlobal("fetch", vi.fn(() => Promise.resolve(jsonResponse({}, 401))));
    const { getAccessToken } = await importToken();

    await expect(getAccessToken()).rejects.toThrow("Not authenticated");
    expect(assign).toHaveBeenCalledWith(LOGIN_URL);
  });
});
