const target=process.env.API_INTERNAL_URL || 'http://localhost:4100';
export default {async rewrites(){return [{source:'/api/:path*',destination:target+'/:path*'}];}};